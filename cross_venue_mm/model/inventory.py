from dataclasses import dataclass

@dataclass
class InventoryState:
    qty: float = 0.0   # base asset
    pv_usd: float = 0.0

class InventorySkew:
    def __init__(self, gamma:float, horizon_secs:int):
        self.gamma = gamma
        self.horizon_secs = horizon_secs
    def reservation_skew(self, sigma_bps:float, inventory_qty:float, px:float)->float:
        # eta ~ gamma * sigma^2 * T ; convert sigma_bps to fraction
        sigma = sigma_bps/1e4
        eta = self.gamma * (sigma**2) * (self.horizon_secs/60)  # scale loosely
        # r = S - eta*q  -> return skew in price units
        return -eta * inventory_qty * px
