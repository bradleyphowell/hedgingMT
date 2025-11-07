from cross_venue_mm.pnl import compute_pnl
from cross_venue_mm.plumbing.types import FillOnX
from cross_venue_mm.execution_y import ExecReport
def test_pnl_sell_then_buy_hedge():
    fill = FillOnX(px=100.10, sz=100, side="sell", ts_ms=0, order_id="x")
    reps = [ExecReport(avg_px=100.05, filled=100, fee_bps=4.0, liquidity="taker")]
    pnl = compute_pnl(fill, reps)
    assert pnl.gross_usd > 0 and pnl.net_usd < pnl.gross_usd  # fees deducted