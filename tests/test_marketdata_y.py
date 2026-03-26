from cross_venue_mm.plumbing.marketdata_y import DepthEvent, MarketDataY


def test_parse_trade_event_preserves_exchange_and_receive_timestamps():
    md = MarketDataY("SUIUSDT")

    trade = md._parse_trade_event(
        {
            "t": 42,
            "p": "0.9254",
            "q": "100",
            "T": 1700000000001,
            "E": 1700000000002,
            "m": True,
        },
        recv_ts_ms=1700000000005,
    )

    assert trade.trade_id == 42
    assert trade.side == "sell"
    assert trade.ts_ms == 1700000000001
    assert trade.event_ts_ms == 1700000000002
    assert trade.recv_ts_ms == 1700000000005


def test_snapshot_plus_depth_update_produces_top_of_book():
    md = MarketDataY("SUIUSDT")
    md._load_snapshot(
        {
            "lastUpdateId": 100,
            "bids": [["100.0", "1.0"], ["99.0", "2.0"]],
            "asks": [["101.0", "1.5"], ["102.0", "3.0"]],
        }
    )

    event = DepthEvent(
        first_update_id=101,
        final_update_id=101,
        bids=[(100.0, 0.0), (99.5, 4.0)],
        asks=[(101.0, 1.0)],
        event_ts_ms=1700000000100,
        recv_ts_ms=1700000000103,
    )

    assert md._apply_depth_event(event)
    book = md._build_book_top(event.event_ts_ms, event.recv_ts_ms, event.final_update_id)

    assert book is not None
    assert book.bid_px == 99.5
    assert book.bid_sz == 4.0
    assert book.ask_px == 101.0
    assert book.ask_sz == 1.0
    assert book.update_id == 101
    assert book.event_ts_ms == 1700000000100
    assert book.recv_ts_ms == 1700000000103


def test_initialize_from_snapshot_applies_buffered_events_in_order():
    md = MarketDataY("SUIUSDT")

    books = md._initialize_from_snapshot(
        {
            "lastUpdateId": 100,
            "bids": [["100.0", "1.0"]],
            "asks": [["101.0", "1.0"]],
        },
        [
            DepthEvent(
                first_update_id=101,
                final_update_id=101,
                bids=[(100.5, 2.0)],
                asks=[],
                event_ts_ms=1700000000200,
                recv_ts_ms=1700000000202,
            )
        ],
    )

    assert len(books) == 1
    assert books[0].bid_px == 100.5
    assert books[0].update_id == 101
