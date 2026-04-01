from .plumbing.config import RiskLimits


class RiskManager:
    def __init__(self, limits:RiskLimits):
        self.limits = limits

    def inventory_notional_usd(self, inventory_qty: float, mark_px: float) -> float:
        return inventory_qty * mark_px

    def check_inventory(self, inventory_qty: float, mark_px: float) -> bool:
        return abs(self.inventory_notional_usd(inventory_qty, mark_px)) <= self.limits.max_inventory_usd

    def check_market_data_health(self, market_data_age_ms: int) -> bool:
        return market_data_age_ms <= self.limits.max_market_data_stale_ms
