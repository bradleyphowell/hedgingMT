import argparse
import asyncio
from contextlib import suppress
import pathlib
import sys
import time

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))

from cross_venue_mm.latency import format_stats, measure_async_ms, measure_sync_ms, summarize_ms
from cross_venue_mm.plumbing.config import AppConfig
from cross_venue_mm.plumbing.types import BookTop, Fill, Trade
from cross_venue_mm.plumbing.wiring import BinanceMarketMakerApp


async def main() -> None:
    base_cfg = AppConfig()

    parser = argparse.ArgumentParser(description="Measure latency across the Binance-only market-making pipeline.")
    parser.add_argument("--symbol", default=base_cfg.symbol, help="Symbol to query, default comes from AppConfig.")
    parser.add_argument("--samples", type=int, default=10, help="Number of latency samples to collect.")
    parser.add_argument("--timeout", type=float, default=20.0, help="Seconds to wait for each websocket event.")
    args = parser.parse_args()

    cfg = AppConfig(symbol=args.symbol)
    app = BinanceMarketMakerApp(cfg)
    clock_offset_ms = app.market_data.estimate_clock_offset_ms()
    book_queue: asyncio.Queue[BookTop] = asyncio.Queue()
    trade_queue: asyncio.Queue[Trade] = asyncio.Queue()

    stage_samples: dict[str, list[float]] = {
        "binance_book_event_latency": [],
        "binance_trade_event_latency": [],
        "binance_trade_match_age": [],
        "quote_compute": [],
        "maker_upsert": [],
        "fill_queue_handoff": [],
        "pnl_apply_fill": [],
        "risk_inventory_check": [],
        "risk_market_data_check": [],
        "decision_to_quote_post": [],
        "synthetic_quote_cycle": [],
    }

    def on_book(book: BookTop) -> None:
        book_queue.put_nowait(book)

    def on_trade(trade: Trade) -> None:
        app.vwap.update(trade.px, trade.sz)
        app.rvol.update(trade.px)
        trade_queue.put_nowait(trade)

    stream_task = asyncio.create_task(app.market_data.run(on_book=on_book, on_trade=on_trade))
    try:
        for i in range(args.samples):
            book = await asyncio.wait_for(book_queue.get(), timeout=args.timeout)
            app.strategy.on_book(book)
            book_event_latency_ms = _event_latency_ms(book.event_ts_ms, book.recv_ts_ms, clock_offset_ms)
            mid_px = (book.bid_px + book.ask_px) / 2
            sigma_bps = app.rvol.sigma_bps()
            inv_skew_px = app.skew.reservation_skew(sigma_bps, app.inventory.qty, mid_px)

            quote_ms, quote = measure_sync_ms(
                app.strategy.make_quote_plan,
                book,
                sigma_bps,
                inv_skew_px,
                cfg.quote.size_usd,
            )
            maker_ms, _ = await measure_async_ms(
                app.maker.upsert_quotes(
                    quote.bid,
                    quote.ask,
                    bid_size=quote.bid_size,
                    ask_size=quote.ask_size,
                )
            )

            fill = Fill(
                px=quote.ask,
                sz=quote.ask_size,
                side="sell",
                ts_ms=int(time.time() * 1000),
                order_id=f"latency-probe-{i}",
            )
            app.maker.record_fill(fill)
            queue_ms, queued_fill = await measure_async_ms(app.maker.next_fill())
            pnl_ms, fill_pnl = measure_sync_ms(app.pnl.apply_fill, queued_fill, fee_bps=cfg.fees.maker_bps)
            app.inventory.qty = app.pnl.position_qty
            risk_inventory_ms, inventory_ok = measure_sync_ms(app.risk.check_inventory, app.inventory.qty, mid_px)
            market_data_age_ms = max(0, int(time.time() * 1000) - (book.recv_ts_ms or book.ts_ms))
            risk_market_data_ms, market_data_ok = measure_sync_ms(
                app.risk.check_market_data_health,
                market_data_age_ms,
            )

            decision_ms = quote_ms + maker_ms
            synthetic_cycle_ms = (
                book_event_latency_ms
                + decision_ms
                + queue_ms
                + pnl_ms
                + risk_inventory_ms
                + risk_market_data_ms
            )

            stage_samples["binance_book_event_latency"].append(book_event_latency_ms)
            stage_samples["quote_compute"].append(quote_ms)
            stage_samples["maker_upsert"].append(maker_ms)
            stage_samples["fill_queue_handoff"].append(queue_ms)
            stage_samples["pnl_apply_fill"].append(pnl_ms)
            stage_samples["risk_inventory_check"].append(risk_inventory_ms)
            stage_samples["risk_market_data_check"].append(risk_market_data_ms)
            stage_samples["decision_to_quote_post"].append(decision_ms)
            stage_samples["synthetic_quote_cycle"].append(synthetic_cycle_ms)

            print(
                f"book_sample={i+1} symbol={args.symbol} "
                f"bid={book.bid_px} ask={book.ask_px} update_id={book.update_id} "
                f"book_event_latency_ms={book_event_latency_ms:.2f} quote_ms={quote_ms:.4f} "
                f"maker_ms={maker_ms:.4f} queue_ms={queue_ms:.4f} pnl_ms={pnl_ms:.4f} "
                f"inventory_ok={inventory_ok} market_data_ok={market_data_ok} "
                f"net_fill_pnl={fill_pnl.net_realized_usd:.6f} synthetic_quote_cycle_ms={synthetic_cycle_ms:.2f}"
            )

        for i in range(args.samples):
            trade = await asyncio.wait_for(trade_queue.get(), timeout=args.timeout)
            trade_event_latency_ms = _event_latency_ms(trade.event_ts_ms, trade.recv_ts_ms, clock_offset_ms)
            trade_match_age_ms = _event_latency_ms(trade.ts_ms, trade.recv_ts_ms, clock_offset_ms)
            stage_samples["binance_trade_event_latency"].append(trade_event_latency_ms)
            stage_samples["binance_trade_match_age"].append(trade_match_age_ms)
            print(
                f"trade_sample={i+1} symbol={args.symbol} "
                f"trade_id={trade.trade_id} px={trade.px} sz={trade.sz} side={trade.side} "
                f"trade_event_latency_ms={trade_event_latency_ms:.2f} trade_match_age_ms={trade_match_age_ms:.2f}"
            )
    finally:
        stream_task.cancel()
        with suppress(asyncio.CancelledError):
            await stream_task

    print("")
    print("Latency Summary")
    print(f"clock_offset_ms={clock_offset_ms:.2f}")
    for label in (
        "binance_book_event_latency",
        "binance_trade_event_latency",
        "binance_trade_match_age",
        "quote_compute",
        "maker_upsert",
        "fill_queue_handoff",
        "pnl_apply_fill",
        "risk_inventory_check",
        "risk_market_data_check",
        "decision_to_quote_post",
        "synthetic_quote_cycle",
    ):
        stats = summarize_ms(stage_samples[label])
        if stats is not None:
            print(format_stats(label, stats))

    print("")
    print("Notes")
    print("- binance_book_event_latency is exchange depth event time to locally received time, adjusted by Binance server-time clock offset.")
    print("- binance_trade_event_latency is exchange trade event time to locally received time, adjusted by Binance server-time clock offset.")
    print("- binance_trade_match_age is matched-trade time to locally received time, adjusted by Binance server-time clock offset.")
    print("- maker_upsert, fill_queue_handoff, pnl_apply_fill, and risk checks are local code-path timings.")


def _event_latency_ms(event_ts_ms: int | None, recv_ts_ms: int | None, clock_offset_ms: float) -> float:
    if event_ts_ms is None or recv_ts_ms is None:
        return 0.0
    return max(0.0, recv_ts_ms + clock_offset_ms - event_ts_ms)


if __name__ == "__main__":
    asyncio.run(main())
