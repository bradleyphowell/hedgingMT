import asyncio

from cross_venue_mm.execution_y import ExecutionY
from cross_venue_mm.hedger import Hedger
from cross_venue_mm.plumbing.config import AppConfig


def test_hedger_posts_maker_with_price_then_qty():
    cfg = AppConfig()
    hedger = Hedger(cfg, ExecutionY(cfg))

    reports = asyncio.run(hedger.hedge_fill("sell", 100.0, 100.0))

    assert len(reports) == 2
    assert reports[0].liquidity == "taker"
    assert reports[1].liquidity == "maker"
    assert reports[1].avg_px < 100.0
    assert reports[1].filled == 50.0
