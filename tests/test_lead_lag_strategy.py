from cross_venue_mm.model.lead_lag_strategy import LeadLagMakerStrategy
from cross_venue_mm.model.quote_engine import QuoteEngine
from cross_venue_mm.plumbing.config import AppConfig
from cross_venue_mm.plumbing.types import BookTop, Trade


def test_neutral_plan_matches_base_quote_when_no_signal():
    cfg = AppConfig()
    qe = QuoteEngine(cfg)
    strategy = LeadLagMakerStrategy(qe)
    book = BookTop(100.0, 10.0, 100.1, 10.0, 1_000)

    strategy.on_book_y(book)
    plan = strategy.make_quote_plan(book, sigma_bps=10.0, inv_skew_px=0.0, size_usd=25_000)
    base = qe.compute(book, sigma_bps=10.0, inv_skew_px=0.0, size_usd=25_000)

    assert plan.mode == "neutral"
    assert plan.bid == base.bid
    assert plan.ask == base.ask
    assert plan.bid_size == plan.ask_size


def test_buy_pressure_biases_quotes_toward_buying_on_maker_venue():
    cfg = AppConfig()
    qe = QuoteEngine(cfg)
    strategy = LeadLagMakerStrategy(qe)
    book = BookTop(100.0, 10.0, 100.1, 10.0, 2_000, event_ts_ms=2_000)

    strategy.on_book_y(book)
    strategy.on_trade_y(Trade(px=100.05, sz=25.0, side="buy", ts_ms=1_000, event_ts_ms=1_000))
    strategy.on_trade_y(Trade(px=100.10, sz=40.0, side="buy", ts_ms=1_200, event_ts_ms=1_200))
    strategy.on_trade_y(Trade(px=100.14, sz=35.0, side="buy", ts_ms=1_400, event_ts_ms=1_400))

    plan = strategy.make_quote_plan(book, sigma_bps=10.0, inv_skew_px=0.0, size_usd=25_000)
    base = qe.compute(book, sigma_bps=10.0, inv_skew_px=0.0, size_usd=25_000)

    assert plan.mode == "buy-lean"
    assert plan.signal_bps > 0.0
    assert plan.bid > base.bid
    assert plan.ask > base.ask
    assert plan.bid_size > plan.ask_size


def test_sell_pressure_biases_quotes_toward_selling_on_maker_venue():
    cfg = AppConfig()
    qe = QuoteEngine(cfg)
    strategy = LeadLagMakerStrategy(qe)
    book = BookTop(100.0, 10.0, 100.1, 10.0, 2_000, event_ts_ms=2_000)

    strategy.on_book_y(book)
    strategy.on_trade_y(Trade(px=100.00, sz=25.0, side="sell", ts_ms=1_000, event_ts_ms=1_000))
    strategy.on_trade_y(Trade(px=99.96, sz=40.0, side="sell", ts_ms=1_200, event_ts_ms=1_200))
    strategy.on_trade_y(Trade(px=99.92, sz=35.0, side="sell", ts_ms=1_400, event_ts_ms=1_400))

    plan = strategy.make_quote_plan(book, sigma_bps=10.0, inv_skew_px=0.0, size_usd=25_000)
    base = qe.compute(book, sigma_bps=10.0, inv_skew_px=0.0, size_usd=25_000)

    assert plan.mode == "sell-lean"
    assert plan.signal_bps < 0.0
    assert plan.bid < base.bid
    assert plan.ask < base.ask
    assert plan.ask_size > plan.bid_size
