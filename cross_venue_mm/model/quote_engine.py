from dataclasses import dataclass
from ..plumbing.config import AppConfig
from .indicators import microprice
from ..plumbing.types import BookTop

@dataclass
class Quote:
    bid: float; ask: float; mid_ref: float; half_spread_bps: float

class QuoteEngine:
    def __init__(self, cfg:AppConfig):
        self.cfg = cfg

    def base_halfspread_bps(self, sigma_bps:float, exp_slippage_bps:float)->float:
        # cover taker fee + expected slippage + a small vol term
        fee = self.cfg.fees_y.taker_bps
        vol_term = max(0.0, 0.35 * sigma_bps**0.5)  # light vol sensitivity
        return fee + exp_slippage_bps + vol_term

    def size_curve_bps(self, size_usd:float)->float:
        # convex size premium: k * (size/25k)^(exp-1)
        k = 1.0
        exp = self.cfg.quote.size_curve_k
        return k * max(0.0, (size_usd / self.cfg.quote.size_usd)**(exp-1))  # bps add-on

    def compute(self, book_y:BookTop, sigma_bps:float, inv_skew_px:float, size_usd:float)->Quote:
        m = microprice(book_y)
        exp_slippage = self._expected_slippage_bps(book_y, size_usd)
        h_bps = self.base_halfspread_bps(sigma_bps, exp_slippage) + self.size_curve_bps(size_usd)
        # reservation price shift:
        r = m + inv_skew_px
        bid = r * (1 - h_bps/1e4)
        ask = r * (1 + h_bps/1e4)
        return Quote(bid=bid, ask=ask, mid_ref=m, half_spread_bps=h_bps)

    def _expected_slippage_bps(self, book:BookTop, size_usd:float)->float:
        # crude: assume cross top, if not enough depth, pay 1-2 bps extra
        top_depth_usd = min(book.bid_sz, book.ask_sz) * ((book.bid_px+book.ask_px)/2)
        return 1.0 if size_usd <= top_depth_usd else 2.0
