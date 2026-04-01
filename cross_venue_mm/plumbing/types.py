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
    update_id: int | None = None
    event_ts_ms: int | None = None
    recv_ts_ms: int | None = None

@dataclass
class Trade:
    px: float
    sz: float
    side: Side
    ts_ms: int
    trade_id: int | None = None
    event_ts_ms: int | None = None
    recv_ts_ms: int | None = None

@dataclass
class Fill:
    px: float
    sz: float
    side: Side  # our perspective; if our resting ask was hit, side="sell"
    ts_ms: int
    order_id: str
