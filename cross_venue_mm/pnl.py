from dataclasses import dataclass
from .plumbing.types import FillOnX
from execution_y import ExecReport

@dataclass
class TradePnL:
    gross_usd: float
    fees_usd: float
    net_usd: float

def compute_pnl(fill_x:FillOnX, hedge_reports:list[ExecReport])->TradePnL:
    # our perspective: if we sold on X at px_x and bought on Y at avg_px (plus fee), edge = (px_x - avg_px)*qty
    qty = fill_x.sz
    px_x = fill_x.px
    gross = 0.0; fees = 0.0
    for r in hedge_reports:
        if fill_x.side == "sell":  # we sold on X, bought on Y
            gross += (px_x - r.avg_px) * (r.filled/qty) * qty
        else:                      # we bought on X, sold on Y
            gross += (r.avg_px - px_x) * (r.filled/qty) * qty
        fees += (r.fee_bps/1e4) * r.avg_px * r.filled
    return TradePnL(gross_usd=gross, fees_usd=fees, net_usd=gross-fees)
