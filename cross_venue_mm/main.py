import asyncio
from .plumbing.config import AppConfig
from .plumbing.wiring import App
from .plumbing.types import FillOnX

async def main():
    cfg = AppConfig()   #defines the configuration in config.py
    app = App(cfg)      #wires up components in wiring.py from above configs

    def on_trade_y(tr):
        app.vwap.update(tr.px, tr.sz)
        app.rvol.update(tr.px)

    def on_book_y(book):
        pass  # could compute microprice if needed here

    async def quoting_loop():
        while True:
            book = app.md_y.last_book()
            if not book:
                await asyncio.sleep(0.05); continue
            sigma_bps = app.rvol.sigma_bps()
            inv_skew_px = app.skew.reservation_skew(sigma_bps, app.inv.qty, (book.bid_px+book.ask_px)/2)
            q = app.qe.compute(book, sigma_bps, inv_skew_px, size_usd=cfg.quote.size_usd)
            await app.maker_x.upsert_quotes(q.bid, q.ask, size=cfg.quote.size_usd/q.mid_ref)
            await asyncio.sleep(cfg.quote.base_refresh_ms/1000)

    async def hedge_on_fill_listener():
        # Pseudocode: subscribe to fills on X
        while True:
            fill = await FillOnX()  # returns FillOnX
            # Hedge at Y using microprice as ref
            book = app.md_y.last_book()
            ref_px = (book.bid_px+book.ask_px)/2 if book else fill.px
            reps = await app.hedger.hedge_fill(fill.side, fill.sz, ref_px)
            # Update inventory
            app.inv.qty += (-fill.sz if fill.side=="sell" else fill.sz)  # we sold -> -qty; we bought -> +qty
            # Compute pnl, log
            # pnl = compute_pnl(fill, reps)  # optional logging

    await asyncio.gather(
        app.md_y.run(on_book=on_book_y, on_trade=on_trade_y),
        quoting_loop(),
        hedge_on_fill_listener(),
    )

if __name__ == "__main__":
    asyncio.run(main())