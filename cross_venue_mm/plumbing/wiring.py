from .config import AppConfig
from .marketdata_y import MarketDataY
from ..model.indicators import RollingVWAP, RollingVol, microprice
from ..model.inventory import InventoryState, InventorySkew
from ..model.quote_engine import QuoteEngine
from ..venue_x_maker import VenueXMaker
from ..execution_y import ExecutionY
from ..hedger import Hedger

class App:
    def __init__(self, cfg:AppConfig):
        self.cfg = cfg
        self.md_y = MarketDataY(cfg.symbol)
        self.vwap = RollingVWAP(200)
        self.rvol = RollingVol(cfg.quote.vol_window_secs)
        self.inv = InventoryState()
        self.skew = InventorySkew(cfg.inv.gamma, cfg.inv.horizon_secs)
        self.qe = QuoteEngine(cfg)
        self.maker_x = VenueXMaker(cfg.symbol, cfg.risk.max_order_rate_per_s)
        self.exec_y = ExecutionY(cfg)
        self.hedger = Hedger(cfg, self.exec_y)