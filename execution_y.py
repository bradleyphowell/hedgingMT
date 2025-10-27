from .config import AppConfig
from .types import Side
from dataclasses import dataclass

""""""""""""""""""""""""""""""""""""""""""""""""""""""""""""""""""""""""""""""""""""""""""""""""""""""""""""""""""""""""""""""
# This module defines the ExecutionY class, which simulates order execution on the liquid hedging venue (Exchange Y).
# It uses configuration parameters from AppConfig to determine fees and limits, and returns structured execution reports.
# The ExecReport dataclass records each hedge’s outcome (average price, filled quantity, fee in bps, and liquidity type).
# The ioc_cross() method models an Immediate-Or-Cancel (IOC) market order used for fast taker hedging, applying a 
# configurable slippage guard around a reference price and including the taker fee (e.g. 4 bps).
# The post_maker() method represents posting a passive maker order at a given price, assuming a fill with zero fees.
# Together, these functions provide a simple abstraction for handling both taker and maker hedge executions on Exchange Y.
""""""""""""""""""""""""""""""""""""""""""""""""""""""""""""""""""""""""""""""""""""""""""""""""""""""""""""""""""""""""""""""


@dataclass
class ExecReport:
    avg_px: float; filled: float; fee_bps: float; liquidity: str  # 'taker' or 'maker'

class ExecutionY:
    def __init__(self, cfg:AppConfig):
        self.cfg = cfg

    async def ioc_cross(self, side:Side, qty:float, ref_px:float, max_slippage_bps:float)->ExecReport:
        # Send IOC/market with price guard: limit = ref_px*(1+/- slippage)
        # Return avg fill px, filled qty, taker fee
        fee = self.cfg.fees_y.taker_bps
        # Pseudocode: result = await venue.order(...)
        return ExecReport(avg_px=ref_px*(1 + (max_slippage_bps/1e4 if side=="buy" else -max_slippage_bps/1e4)),
                          filled=qty, fee_bps=fee, liquidity="taker")

    async def post_maker(self, side:Side, px:float, qty:float)->ExecReport:
        # Post passive; here we simulate immediate pass for outline
        return ExecReport(avg_px=px, filled=qty, fee_bps=0.0, liquidity="maker")
