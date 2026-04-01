from cross_venue_mm.plumbing.config import RiskLimits
from cross_venue_mm.risk import RiskManager


def test_risk_manager_checks_inventory_notional():
    risk = RiskManager(RiskLimits(max_inventory_usd=1000.0, max_order_rate_per_s=5.0, max_market_data_stale_ms=3000))

    assert risk.check_inventory(5.0, 150.0)
    assert not risk.check_inventory(10.0, 150.0)


def test_risk_manager_checks_market_data_staleness():
    risk = RiskManager(RiskLimits(max_inventory_usd=1000.0, max_order_rate_per_s=5.0, max_market_data_stale_ms=500))

    assert risk.check_market_data_health(250)
    assert not risk.check_market_data_health(750)
