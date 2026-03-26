import argparse
import asyncio
from contextlib import suppress
import pathlib
import sys
import time

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))

from cross_venue_mm.execution_y import ExecutionY
from cross_venue_mm.hedger import Hedger
from cross_venue_mm.latency import format_stats, measure_async_ms, measure_sync_ms, summarize_ms
from cross_venue_mm.model.quote_engine import QuoteEngine
from cross_venue_mm.plumbing.config import AppConfig
from cross_venue_mm.plumbing.marketdata_y import MarketDataY
from cross_venue_mm.plumbing.types import BookTop, FillOnX, Trade
from cross_venue_mm.venue_x_maker import VenueXMaker


async def main() -> None:
    cfg = AppConfig()

    parser = argparse.ArgumentParser(description="Measure latency across the current market-making pipeline.")
    parser.add_argument("--symbol", default=cfg.symbol, help="Symbol to query, default comes from AppConfig.")
    parser.add_argument("--samples", type=int, default=10, help="Number of latency samples to collect.")
    parser.add_argument("--timeout", type=float, default=20.0, help="Seconds to wait for each websocket event.")
    args = parser.parse_args()

    md_y = MarketDataY(args.symbol)
    clock_offset_ms = md_y.estimate_clock_offset_ms()
    qe = QuoteEngine(cfg)
    maker_x = VenueXMaker(args.symbol, cfg.risk.max_order_rate_per_s)
    hedger = Hedger(cfg, ExecutionY(cfg))
    book_queue: asyncio.Queue[BookTop] = asyncio.Queue()
    trade_queue: asyncio.Queue[Trade] = asyncio.Queue()

    stage_samples: dict[str, list[float]] = {
        "venue_y_book_event_latency": [],
        "venue_y_trade_event_latency": [],
        "venue_y_trade_match_age": [],
        "quote_compute": [],
        "maker_upsert": [],
        "fill_queue_handoff": [],
        "hedge_fill": [],
        "decision_to_quote_post": [],
        "synthetic_quote_cycle": [],
    }

    def on_book(book: BookTop) -> None:
        book_queue.put_nowait(book)

    def on_trade(trade: Trade) -> None:
        trade_queue.put_nowait(trade)

    stream_task = asyncio.create_task(md_y.run(on_book=on_book, on_trade=on_trade))
    try:
        for i in range(args.samples):
            book = await asyncio.wait_for(book_queue.get(), timeout=args.timeout)
            book_event_latency_ms = _event_latency_ms(book.event_ts_ms, book.recv_ts_ms, clock_offset_ms)

            quote_ms, quote = measure_sync_ms(
                qe.compute,
                book,
                0.0,
                0.0,
                cfg.quote.size_usd,
            )
            quote_size = cfg.quote.size_usd / quote.mid_ref
            maker_ms, _ = await measure_async_ms(maker_x.upsert_quotes(quote.bid, quote.ask, quote_size))

            fill = FillOnX(
                px=quote.ask,
                sz=quote_size,
                side="sell",
                ts_ms=int(time.time() * 1000),
                order_id=f"latency-probe-{i}",
            )
            maker_x.record_fill(fill)
            queue_ms, queued_fill = await measure_async_ms(maker_x.next_fill())
            hedge_ms, hedge_reports = await measure_async_ms(
                hedger.hedge_fill(queued_fill.side, queued_fill.sz, quote.mid_ref)
            )

            decision_ms = quote_ms + maker_ms
            synthetic_cycle_ms = book_event_latency_ms + decision_ms + queue_ms + hedge_ms

            stage_samples["venue_y_book_event_latency"].append(book_event_latency_ms)
            stage_samples["quote_compute"].append(quote_ms)
            stage_samples["maker_upsert"].append(maker_ms)
            stage_samples["fill_queue_handoff"].append(queue_ms)
            stage_samples["hedge_fill"].append(hedge_ms)
            stage_samples["decision_to_quote_post"].append(decision_ms)
            stage_samples["synthetic_quote_cycle"].append(synthetic_cycle_ms)

            print(
                f"book_sample={i+1} symbol={args.symbol} "
                f"bid={book.bid_px} ask={book.ask_px} update_id={book.update_id} "
                f"book_event_latency_ms={book_event_latency_ms:.2f} quote_ms={quote_ms:.4f} "
                f"maker_ms={maker_ms:.4f} queue_ms={queue_ms:.4f} hedge_ms={hedge_ms:.4f} "
                f"hedges={len(hedge_reports)} synthetic_quote_cycle_ms={synthetic_cycle_ms:.2f}"
            )

        for i in range(args.samples):
            trade = await asyncio.wait_for(trade_queue.get(), timeout=args.timeout)
            trade_event_latency_ms = _event_latency_ms(trade.event_ts_ms, trade.recv_ts_ms, clock_offset_ms)
            trade_match_age_ms = _event_latency_ms(trade.ts_ms, trade.recv_ts_ms, clock_offset_ms)
            stage_samples["venue_y_trade_event_latency"].append(trade_event_latency_ms)
            stage_samples["venue_y_trade_match_age"].append(trade_match_age_ms)
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
        "venue_y_book_event_latency",
        "venue_y_trade_event_latency",
        "venue_y_trade_match_age",
        "quote_compute",
        "maker_upsert",
        "fill_queue_handoff",
        "hedge_fill",
        "decision_to_quote_post",
        "synthetic_quote_cycle",
    ):
        stats = summarize_ms(stage_samples[label])
        if stats is not None:
            print(format_stats(label, stats))

    print("")
    print("Notes")
    print("- venue_y_book_event_latency is exchange depth event time to locally received time, adjusted by Binance server-time clock offset.")
    print("- venue_y_trade_event_latency is exchange trade event time to locally received time, adjusted by Binance server-time clock offset.")
    print("- venue_y_trade_match_age is matched-trade time to locally received time, adjusted by Binance server-time clock offset.")
    print("- maker_upsert, fill_queue_handoff, and hedge_fill are local code-path timings because venue X and execution Y are still stubs.")


def _event_latency_ms(event_ts_ms: int | None, recv_ts_ms: int | None, clock_offset_ms: float) -> float:
    if event_ts_ms is None or recv_ts_ms is None:
        return 0.0
    return max(0.0, recv_ts_ms + clock_offset_ms - event_ts_ms)


if __name__ == "__main__":
    asyncio.run(main())
