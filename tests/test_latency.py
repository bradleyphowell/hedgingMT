from cross_venue_mm.latency import format_stats, measure_sync_ms, summarize_ms


def test_measure_sync_ms_returns_result():
    elapsed_ms, result = measure_sync_ms(sum, [1, 2, 3])

    assert result == 6
    assert elapsed_ms >= 0.0


def test_summarize_ms_computes_basic_stats():
    stats = summarize_ms([1.0, 2.0, 3.0, 4.0])

    assert stats is not None
    assert stats.count == 4
    assert stats.min_ms == 1.0
    assert stats.max_ms == 4.0
    assert stats.p50_ms == 2.5
    assert format_stats("stage", stats).startswith("stage: count=4 ")
