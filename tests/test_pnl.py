from math import isclose

from cross_venue_mm.pnl import PnLTracker
from cross_venue_mm.plumbing.types import Fill


def test_pnl_tracker_realizes_profit_when_reducing_long():
    pnl = PnLTracker()
    pnl.apply_fill(Fill(px=100.0, sz=2.0, side="buy", ts_ms=1, order_id="buy-1"))

    fill_pnl = pnl.apply_fill(Fill(px=101.5, sz=1.0, side="sell", ts_ms=2, order_id="sell-1"), fee_bps=4.0)

    assert isclose(fill_pnl.realized_usd, 1.5)
    assert fill_pnl.fee_usd > 0.0
    assert isclose(fill_pnl.position_qty, 1.0)
    assert isclose(fill_pnl.average_entry_px, 100.0)


def test_pnl_tracker_marks_open_inventory_to_market():
    pnl = PnLTracker()
    pnl.apply_fill(Fill(px=100.0, sz=2.0, side="buy", ts_ms=1, order_id="buy-1"))
    marked = pnl.mark_to_market(101.25)

    assert isclose(marked.unrealized_usd, 2.5)
    assert isclose(marked.net_usd, 2.5)
    assert isclose(marked.position_qty, 2.0)
