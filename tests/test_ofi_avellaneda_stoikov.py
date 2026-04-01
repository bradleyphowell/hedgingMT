from cross_venue_mm.model.ofi_avellaneda_stoikov import (
    OFIAvellanedaStoikovParams,
    OFIAvellanedaStoikovStrategy,
    OrderFlowImbalance,
)
from cross_venue_mm.model.quote_engine import QuoteEngine
from cross_venue_mm.plumbing.config import AppConfig
from cross_venue_mm.plumbing.types import BookTop


def test_order_flow_imbalance_turns_positive_on_bid_strength():
    ofi = OrderFlowImbalance(window_ms=5_000)
    ofi.update(BookTop(100.0, 10.0, 100.1, 10.0, 1_000))
    ofi.update(BookTop(100.1, 15.0, 100.1, 10.0, 1_100))

    assert ofi.value() > 0.0


def test_order_flow_imbalance_drops_samples_outside_time_window():
    ofi = OrderFlowImbalance(window_ms=150)
    ofi.update(BookTop(100.0, 10.0, 100.1, 10.0, 1_000))
    ofi.update(BookTop(100.1, 15.0, 100.1, 10.0, 1_100))

    assert ofi.value(now_ts_ms=1_100) > 0.0
    assert ofi.value(now_ts_ms=1_300) == 0.0


def test_ofi_strategy_stays_neutral_below_trigger():
    cfg = AppConfig()
    qe = QuoteEngine(cfg)
    strategy = OFIAvellanedaStoikovStrategy(
        qe,
        OFIAvellanedaStoikovParams(ofi_window_ms=5_000, ofi_trigger=0.50, max_aggression_bps=3.0),
    )
    book = BookTop(100.0, 10.0, 100.1, 10.0, 1_000)
    strategy.on_book_y(book)
    strategy.on_book_y(BookTop(100.0, 10.5, 100.1, 9.5, 1_100))

    plan = strategy.make_quote_plan(book, sigma_bps=10.0, inv_skew_px=0.0, size_usd=25_000)
    base = qe.compute(book, sigma_bps=10.0, inv_skew_px=0.0, size_usd=25_000)

    assert plan.mode == "neutral"
    assert plan.bid == base.bid
    assert plan.ask == base.ask


def test_positive_ofi_makes_bid_aggressive_and_ask_defensive():
    cfg = AppConfig()
    qe = QuoteEngine(cfg)
    strategy = OFIAvellanedaStoikovStrategy(
        qe,
        OFIAvellanedaStoikovParams(ofi_window_ms=5_000, ofi_trigger=0.10, max_aggression_bps=3.0),
    )
    book = BookTop(100.0, 10.0, 100.1, 10.0, 1_000)

    strategy.on_book_y(book)
    strategy.on_book_y(BookTop(100.1, 18.0, 100.1, 10.0, 1_100))
    strategy.on_book_y(BookTop(100.1, 20.0, 100.1, 9.0, 1_200))

    plan = strategy.make_quote_plan(book, sigma_bps=10.0, inv_skew_px=0.0, size_usd=25_000)
    base = qe.compute(book, sigma_bps=10.0, inv_skew_px=0.0, size_usd=25_000)

    assert plan.mode == "buy-lean"
    assert plan.ofi_value > 0.0
    assert plan.bid > base.bid
    assert plan.ask > base.ask


def test_negative_ofi_makes_ask_aggressive_and_bid_defensive():
    cfg = AppConfig()
    qe = QuoteEngine(cfg)
    strategy = OFIAvellanedaStoikovStrategy(
        qe,
        OFIAvellanedaStoikovParams(ofi_window_ms=5_000, ofi_trigger=0.10, max_aggression_bps=3.0),
    )
    book = BookTop(100.0, 10.0, 100.1, 10.0, 1_000)

    strategy.on_book_y(book)
    strategy.on_book_y(BookTop(100.0, 9.0, 100.0, 18.0, 1_100))
    strategy.on_book_y(BookTop(100.0, 8.0, 100.0, 20.0, 1_200))

    plan = strategy.make_quote_plan(book, sigma_bps=10.0, inv_skew_px=0.0, size_usd=25_000)
    base = qe.compute(book, sigma_bps=10.0, inv_skew_px=0.0, size_usd=25_000)

    assert plan.mode == "sell-lean"
    assert plan.ofi_value < 0.0
    assert plan.bid < base.bid
    assert plan.ask < base.ask
