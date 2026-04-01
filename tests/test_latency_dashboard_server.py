from collections import deque

from cross_venue_mm.latency_dashboard_server import build_latency_rows, build_latency_summary


def _rows_by_key(rows):
    return {row["key"]: row for row in rows}


def test_build_latency_rows_reports_live_idle_and_placeholder_stages():
    samples = {
        "book_event_latency_ms": deque([10.0, 20.0, 30.0]),
    }
    last_values = {
        "book_event_latency_ms": 30.0,
    }

    rows = _rows_by_key(build_latency_rows(samples, last_values))

    assert rows["book_event_latency_ms"]["status"] == "live"
    assert rows["book_event_latency_ms"]["count"] == 3
    assert rows["book_event_latency_ms"]["lastMs"] == 30.0
    assert rows["book_event_latency_ms"]["p50Ms"] == 20.0

    assert rows["quote_compute_ms"]["status"] == "idle"
    assert rows["quote_compute_ms"]["count"] == 0
    assert rows["quote_compute_ms"]["p95Ms"] is None

    assert rows["order_ack_latency_ms"]["status"] == "placeholder"
    assert rows["order_ack_latency_ms"]["lastMs"] is None


def test_build_latency_summary_includes_queue_depth_and_key_percentiles():
    samples = {
        "book_event_latency_ms": deque([12.0, 20.0, 30.0]),
        "trade_event_latency_ms": deque([8.0, 9.0, 12.0]),
        "book_processing_ms": deque([1.0, 2.0, 4.0]),
        "quote_compute_ms": deque([0.5, 0.7, 0.9]),
        "maker_upsert_ms": deque([0.8, 1.2, 2.4]),
        "decision_to_quote_ms": deque([4.0, 6.0, 8.0]),
    }

    summary = build_latency_summary(
        samples,
        book_rate_per_s=11.5,
        trade_rate_per_s=24.0,
        current_book_age_ms=73.0,
        book_queue_depth=2,
        trade_queue_depth=1,
    )

    assert summary["bookEventP50Ms"] == 20.0
    assert summary["tradeEventP50Ms"] == 9.0
    assert summary["quoteCreateP50Ms"] == 0.7
    assert summary["bookProcessP95Ms"] == 3.8
    assert summary["makerUpsertP95Ms"] == 2.28
    assert summary["decisionToQuoteP95Ms"] == 7.8
    assert summary["bookRatePerSec"] == 11.5
    assert summary["tradeRatePerSec"] == 24.0
    assert summary["currentBookAgeMs"] == 73.0
    assert summary["bookQueueDepth"] == 2
    assert summary["tradeQueueDepth"] == 1
    assert summary["orderAckMs"] is None
