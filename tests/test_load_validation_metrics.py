from app.evaluation.load_validation import summarize_latencies


def test_summarize_latencies_uses_nearest_rank_percentiles() -> None:
    summary = summarize_latencies(
        [10.0, 20.0, 30.0, 40.0, 100.0],
        success_count=4,
        elapsed_ms=200.0,
        peak_concurrency=3,
    )

    assert summary.request_count == 5
    assert summary.success_count == 4
    assert summary.failure_count == 1
    assert summary.success_rate == 0.8
    assert summary.throughput_rps == 25.0
    assert summary.p50_ms == 30.0
    assert summary.p95_ms == 100.0
    assert summary.max_ms == 100.0
    assert summary.peak_concurrency == 3


def test_summarize_latencies_handles_an_empty_sample() -> None:
    summary = summarize_latencies(
        [],
        success_count=0,
        elapsed_ms=0,
        peak_concurrency=0,
    )

    assert summary.request_count == 0
    assert summary.success_rate == 0.0
    assert summary.throughput_rps == 0.0
    assert summary.p95_ms == 0.0


def test_summarize_latencies_bounds_invalid_counts() -> None:
    summary = summarize_latencies(
        [5.0, 7.0],
        success_count=7,
        elapsed_ms=10.0,
        peak_concurrency=-2,
    )

    assert summary.success_count == 2
    assert summary.failure_count == 0
    assert summary.peak_concurrency == 0
