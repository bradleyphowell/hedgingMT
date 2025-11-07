from cross_venue_mm.model.quote_engine import QuoteEngine
from cross_venue_mm.plumbing.config import AppConfig
from cross_venue_mm.plumbing.types import BookTop
def test_quote_widens_with_sigma():
    qe = QuoteEngine(AppConfig())
    book = BookTop(100,10,100.1,10,0)
    q1 = qe.compute(book, sigma_bps=10, inv_skew_px=0.0, size_usd=25_000)
    q2 = qe.compute(book, sigma_bps=50, inv_skew_px=0.0, size_usd=25_000)
    assert (q2.ask - q2.bid) > (q1.ask - q1.bid)