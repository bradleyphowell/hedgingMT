import asyncio
from collections import deque
from math import isclose

from cross_venue_mm.dashboard_server import (
    append_price_point,
    append_public_trade,
    book_top_from_binance_depth,
    make_dashboard_quote_plan,
    normalize_account_snapshot,
    normalize_binance_depth,
    normalize_public_trade,
    normalize_working_quotes,
    resolve_market_selection,
    trade_from_binance_trade,
)
from cross_venue_mm.plumbing.config import AppConfig
from cross_venue_mm.plumbing.types import BookTop, Fill, Trade
from cross_venue_mm.plumbing.wiring import App
from cross_venue_mm.venue_x_maker import WorkingQuote, WorkingQuotes


def test_resolve_market_selection_maps_coin_to_exchange_symbols():
    selection = resolve_market_selection("sui")

    assert selection.market == "SUI"
    assert selection.binance_symbol == "SUIUSDT"


def test_resolve_market_selection_accepts_binance_style_symbol():
    selection = resolve_market_selection("BTCUSDT")

    assert selection.market == "BTC"
    assert selection.binance_symbol == "BTCUSDT"


def test_normalize_binance_depth_keeps_top_levels():
    payload = {
        "lastUpdateId": 123,
        "bids": [["100.0", "5"], ["99.9", "4"]],
        "asks": [["100.1", "6"], ["100.2", "7"]],
    }

    normalized = normalize_binance_depth(payload, "SUIUSDT", recv_ts_ms=1000)

    assert normalized["label"] == "Binance Spot"
    assert normalized["symbol"] == "SUIUSDT"
    assert normalized["sequence"] == 123
    assert normalized["bids"][0]["px"] == 100.0
    assert normalized["asks"][0]["sz"] == 6.0

def test_book_top_from_binance_depth_extracts_best_levels():
    payload = {
        "lastUpdateId": 123,
        "bids": [["100.0", "5"], ["99.9", "4"]],
        "asks": [["100.1", "6"], ["100.2", "7"]],
    }

    book = book_top_from_binance_depth(payload, recv_ts_ms=1500)

    assert book is not None
    assert book.bid_px == 100.0
    assert book.bid_sz == 5.0
    assert book.ask_px == 100.1
    assert book.ask_sz == 6.0
    assert book.update_id == 123


def test_trade_from_binance_trade_maps_taker_side():
    trade = trade_from_binance_trade(
        {"t": 77, "p": "100.5", "q": "12.5", "T": 2000, "E": 2010, "m": True},
        recv_ts_ms=2020,
    )

    assert trade.trade_id == 77
    assert trade.side == "sell"
    assert trade.px == 100.5
    assert trade.sz == 12.5
    assert trade.ts_ms == 2000
    assert trade.event_ts_ms == 2010


def test_normalize_working_quotes_serializes_bid_and_ask():
    normalized = normalize_working_quotes(
        WorkingQuotes(
            bid=WorkingQuote(px=100.0, qty=5.0, order_id="bid-1"),
            ask=WorkingQuote(px=100.2, qty=4.5, order_id="ask-1"),
        ),
        symbol="SUI",
        mode="buy-lean",
        ofi_value=0.42,
    )

    assert normalized["status"] == "live"
    assert normalized["mode"] == "buy-lean"
    assert normalized["ofiValue"] == 0.42
    assert normalized["bid"]["px"] == 100.0
    assert normalized["bid"]["sz"] == 5.0
    assert normalized["ask"]["px"] == 100.2
    assert normalized["ask"]["orderId"] == "ask-1"
    assert isclose(normalized["quotedSpreadBps"], 19.980019980019982)


def test_dashboard_quote_snapshot_uses_quantized_sui_prices():
    app = App(AppConfig(symbol="SUIUSDT"))

    asyncio.run(app.maker.upsert_quotes(0.8804830481941519, 0.8818167280375141, bid_size=5.0, ask_size=4.5))
    normalized = normalize_working_quotes(
        app.maker.working_quotes(),
        symbol="SUI",
        mode="neutral",
        ofi_value=0.0,
    )

    assert normalized["bid"]["px"] == 0.8804
    assert normalized["ask"]["px"] == 0.8819


def test_normalize_account_snapshot_reports_live_pnl_and_exposure():
    app = App(AppConfig(symbol="SUIUSDT"))
    app.pnl.apply_fill(Fill(px=100.0, sz=2.0, side="buy", ts_ms=1, order_id="fill-1"), fee_bps=4.0)
    asyncio.run(app.maker.upsert_quotes(99.9, 100.1, bid_size=3.0, ask_size=4.0))

    snapshot = normalize_account_snapshot(app, app.maker.working_quotes(), mark_px=101.0)

    assert snapshot["positionSide"] == "long"
    assert snapshot["positionQty"] == 2.0
    assert snapshot["averageEntryPx"] == 100.0
    assert isclose(snapshot["exposureUsd"], 202.0)
    assert isclose(snapshot["grossExposureUsd"], 202.0)
    assert isclose(snapshot["unrealizedUsd"], 2.0)
    assert snapshot["netUsd"] < snapshot["unrealizedUsd"]
    assert isclose(snapshot["workingTotalUsd"], (99.9 * 3.0) + (100.1 * 4.0))


def test_normalize_public_trade_keeps_public_tape_fields():
    normalized = normalize_public_trade(
        Trade(px=100.5, sz=12.5, side="buy", ts_ms=2000, trade_id=77, event_ts_ms=2010, recv_ts_ms=2020),
    )

    assert normalized["tradeId"] == 77
    assert normalized["side"] == "buy"
    assert normalized["px"] == 100.5
    assert normalized["sz"] == 12.5
    assert normalized["tsMs"] == 2010


def test_append_public_trade_keeps_last_ten_newest_first():
    recent_trades = deque(maxlen=10)

    for idx in range(12):
        append_public_trade(
            recent_trades,
            Trade(px=100.0 + idx, sz=1.0 + idx, side="buy" if idx % 2 == 0 else "sell", ts_ms=1000 + idx, trade_id=idx),
        )

    assert len(recent_trades) == 10
    assert recent_trades[0]["tradeId"] == 11
    assert recent_trades[-1]["tradeId"] == 2


def test_append_price_point_buckets_by_second_and_prunes_old_history():
    price_history = deque()

    append_price_point(price_history, Trade(px=100.0, sz=1.0, side="buy", ts_ms=1000, trade_id=1))
    append_price_point(price_history, Trade(px=101.0, sz=1.0, side="sell", ts_ms=1500, trade_id=2))
    append_price_point(price_history, Trade(px=102.0, sz=1.0, side="buy", ts_ms=600000, trade_id=3))
    append_price_point(price_history, Trade(px=103.0, sz=1.0, side="buy", ts_ms=602000, trade_id=4))

    assert len(price_history) == 2
    assert price_history[0]["tsMs"] == 600000
    assert price_history[0]["px"] == 102.0
    assert price_history[-1]["px"] == 103.0


def test_make_dashboard_quote_plan_uses_ofi_strategy_preview():
    app = App(AppConfig(symbol="SUIUSDT"))
    book = BookTop(bid_px=100.0, bid_sz=10.0, ask_px=100.1, ask_sz=10.0, ts_ms=1000)

    app.lead_lag_strategy.on_book(book)
    app.lead_lag_strategy.on_trade(
        Trade(px=100.2, sz=1.0, side="buy", ts_ms=1010, event_ts_ms=1010, recv_ts_ms=1010),
    )
    app.strategy.on_book(book)

    lead_lag_plan = app.lead_lag_strategy.make_quote_plan(
        book,
        sigma_bps=0.0,
        inv_skew_px=0.0,
        size_usd=app.cfg.quote.size_usd,
    )
    plan = make_dashboard_quote_plan(app, book)

    assert lead_lag_plan.mode == "buy-lean"
    assert plan.mode == "neutral"
