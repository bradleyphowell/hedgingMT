import os

from .binanceintegration import BinanceIntegration
from .config import AppConfig
from .marketdata_y import BinanceMarketData
from ..model.indicators import RollingVWAP, RollingVol
from ..model.inventory import InventoryState, InventorySkew
from ..model.lead_lag_strategy import LeadLagMakerStrategy
from ..model.ofi_avellaneda_stoikov import OFIAvellanedaStoikovStrategy
from ..model.quote_engine import QuoteEngine
from ..pnl import PnLTracker
from ..risk import RiskManager
from ..venue_x_maker import BinanceMaker


class BinanceMarketMakerApp:
    def __init__(self, cfg: AppConfig):
        self.cfg = cfg
        self.market_data = BinanceMarketData(cfg.symbol)
        self.vwap = RollingVWAP(200)
        self.rvol = RollingVol(cfg.quote.vol_window_secs)
        self.inventory = InventoryState()
        self.skew = InventorySkew(cfg.inv.gamma, cfg.inv.horizon_secs)
        self.quote_engine = QuoteEngine(cfg)
        self.lead_lag_strategy = LeadLagMakerStrategy(self.quote_engine)
        self.ofi_strategy = OFIAvellanedaStoikovStrategy(self.quote_engine, cfg.ofi)
        self.strategy = self.ofi_strategy
        self.maker = BinanceMaker(cfg.symbol, cfg.risk.max_order_rate_per_s, price_tick=cfg.maker_price_tick())
        self.integration = BinanceIntegration(
            api_key=os.getenv("BINANCE_API_KEY"),
            api_secret=os.getenv("BINANCE_API_SECRET"),
            symbol=cfg.symbol,
        )
        self.risk = RiskManager(cfg.risk)
        self.pnl = PnLTracker()


App = BinanceMarketMakerApp
