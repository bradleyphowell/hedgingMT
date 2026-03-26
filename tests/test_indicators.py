from cross_venue_mm.model.indicators import RollingVWAP, microprice
from cross_venue_mm.plumbing.types import BookTop
def test_microprice_biases_toward_imbalanced_side():
    b = BookTop(bid_px=100, bid_sz=200, ask_px=100.1, ask_sz=100, ts_ms=0)
    m = microprice(b)
    assert m > (100+100.1)/2  # more bid depth -> microprice > mid

def test_rolling_vwap_evicts_old_trades():
    vwap = RollingVWAP(n_trades=2)
    vwap.update(100.0, 1.0)
    vwap.update(110.0, 1.0)
    vwap.update(120.0, 1.0)
    assert vwap.value == 115.0
