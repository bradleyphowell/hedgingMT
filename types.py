from dataclasses import dataclass
from typing import Literal

Side = Literal["buy", "sell"]

@dataclass
class BookTop:
    bid_px: float
    bid_sz: float
    ask_px: float
    ask_sz: float
    ts_ms: int

@dataclass
class Trade:
    px: float
    sz: float
    side: Side  # taker side on Y
    ts_ms: int

@dataclass
class FillOnX:
    px: float
    sz: float
    side: Side  # our perspective on X: if we were lifted, side="sell"
    ts_ms: int
    order_id: str
