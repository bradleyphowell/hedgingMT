from dataclasses import dataclass
from typing import Optional

@dataclass(frozen=True)
class VenueFees:
    maker_bps: float = 0.0
    taker_bps: float = 4.0  # Exchange Y taker fee

@dataclass(frozen=True)
class HedgePolicy:
    taker_fraction: float = 0.5       # % of fill to hedge immediately as taker
    maker_timeout_ms: int = 1500      # wait before crossing remainder
    max_slippage_bps: float = 3.0     # cap adverse slippage when crossing
    clip_usd: float = 50_000          # max IOC clip size
    post_bps_from_micro: float = 1.0  # for maker posting

@dataclass(frozen=True)
class RiskLimits:
    max_inventory_usd: float = 10000.0
    max_order_rate_per_s: float = 5.0
    max_venue_y_down_ms: int = 3000

@dataclass(frozen=True)
class QuoteParams:
    base_refresh_ms: int = 250
    epsilon_move_bps: float = 1.0     # price change to refresh quotes
    vol_window_secs: int = 300        # for realized vol
    size_usd: float = 25_000          # default quote size on X
    size_curve_k: float = 1.6         # convexity exponent > 1

@dataclass(frozen=True)
class InventoryParams:
    gamma: float = 0.5
    # scales reservation-price skew ~ eta ~ gamma * sigma^2 * horizon
    horizon_secs: int = 300

@dataclass(frozen=True)
class AppConfig:
    symbol: str = "SUIUSDT"
    venue_x: str = "ExchangeX"
    venue_y: str = "ExchangeY"
    fees_y: VenueFees = VenueFees()
    hedge: HedgePolicy = HedgePolicy()
    risk: RiskLimits = RiskLimits()
    quote: QuoteParams = QuoteParams()
    inv: InventoryParams = InventoryParams()
