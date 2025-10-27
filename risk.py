from .config import RiskLimits

class RiskManager:
    def __init__(self, limits:RiskLimits):
        self.limits = limits
    def check_inventory(self, inventory_usd:float)->bool:
        return abs(inventory_usd) <= self.limits.max_inventory_usd
    def check_venue_health(self, venue_y_latency_ms:int)->bool:
        return venue_y_latency_ms <= self.limits.max_venue_y_down_ms
