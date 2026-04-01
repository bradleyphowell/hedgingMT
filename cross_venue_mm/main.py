import asyncio
import time

from .plumbing.config import AppConfig
from .plumbing.wiring import BinanceMarketMakerApp


async def main() -> None:
    cfg = AppConfig()
    app = BinanceMarketMakerApp(cfg)

    def on_trade(trade) -> None:
        app.vwap.update(trade.px, trade.sz)
        app.rvol.update(trade.px)

    def on_book(book) -> None:
        app.strategy.on_book(book)

    async def quoting_loop() -> None:
        while True:
            book = app.market_data.last_book()
            if book is None:
                await asyncio.sleep(0.05)
                continue

            market_data_age_ms = max(0, int(time.time() * 1000) - (book.recv_ts_ms or book.ts_ms))
            if not app.risk.check_market_data_health(market_data_age_ms):
                await app.maker.cancel_all()
                await asyncio.sleep(cfg.quote.base_refresh_ms / 1000)
                continue

            mid_px = (book.bid_px + book.ask_px) / 2
            if not app.risk.check_inventory(app.inventory.qty, mid_px):
                await app.maker.cancel_all()
                await asyncio.sleep(cfg.quote.base_refresh_ms / 1000)
                continue

            sigma_bps = app.rvol.sigma_bps()
            inv_skew_px = app.skew.reservation_skew(sigma_bps, app.inventory.qty, mid_px)
            plan = app.strategy.make_quote_plan(book, sigma_bps, inv_skew_px, size_usd=cfg.quote.size_usd)
            await app.maker.upsert_quotes(
                plan.bid,
                plan.ask,
                bid_size=plan.bid_size,
                ask_size=plan.ask_size,
            )
            await asyncio.sleep(cfg.quote.base_refresh_ms / 1000)

    async def fill_listener() -> None:
        while True:
            fill = await app.maker.next_fill()
            fee_bps = cfg.fees.maker_bps
            app.pnl.apply_fill(fill, fee_bps=fee_bps)
            app.inventory.qty = app.pnl.position_qty

    await asyncio.gather(
        app.market_data.run(on_book=on_book, on_trade=on_trade),
        quoting_loop(),
        fill_listener(),
    )


if __name__ == "__main__":
    asyncio.run(main())
