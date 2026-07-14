from __future__ import annotations

from dataclasses import asdict, dataclass
from math import ceil


@dataclass(frozen=True)
class LoadSummary:
    request_count: int
    success_count: int
    failure_count: int
    success_rate: float
    throughput_rps: float
    p50_ms: float
    p95_ms: float
    max_ms: float
    peak_concurrency: int

    def as_public_dict(self) -> dict[str, int | float]:
        return asdict(self)


def _nearest_rank(values: list[float], quantile: float) -> float:
    if not values:
        return 0.0
    ordered = sorted(values)
    index = max(0, ceil(quantile * len(ordered)) - 1)
    return round(ordered[index], 3)


def summarize_latencies(
    latencies_ms: list[float],
    *,
    success_count: int,
    elapsed_ms: float,
    peak_concurrency: int,
) -> LoadSummary:
    request_count = len(latencies_ms)
    bounded_success = min(max(success_count, 0), request_count)
    throughput_rps = (
        round(request_count / (elapsed_ms / 1000), 3) if elapsed_ms > 0 else 0.0
    )
    return LoadSummary(
        request_count=request_count,
        success_count=bounded_success,
        failure_count=request_count - bounded_success,
        success_rate=(
            round(bounded_success / request_count, 4) if request_count else 0.0
        ),
        throughput_rps=throughput_rps,
        p50_ms=_nearest_rank(latencies_ms, 0.50),
        p95_ms=_nearest_rank(latencies_ms, 0.95),
        max_ms=round(max(latencies_ms), 3) if latencies_ms else 0.0,
        peak_concurrency=max(peak_concurrency, 0),
    )
