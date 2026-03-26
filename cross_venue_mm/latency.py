from dataclasses import dataclass
from math import ceil, floor
from statistics import mean
from time import perf_counter_ns
from typing import Awaitable, Callable, Sequence, TypeVar

T = TypeVar("T")


@dataclass(frozen=True)
class LatencyStats:
    count: int
    min_ms: float
    p50_ms: float
    p95_ms: float
    max_ms: float
    mean_ms: float


def measure_sync_ms(fn: Callable[..., T], *args, **kwargs) -> tuple[float, T]:
    started_ns = perf_counter_ns()
    result = fn(*args, **kwargs)
    elapsed_ms = (perf_counter_ns() - started_ns) / 1_000_000
    return elapsed_ms, result


async def measure_async_ms(awaitable: Awaitable[T]) -> tuple[float, T]:
    started_ns = perf_counter_ns()
    result = await awaitable
    elapsed_ms = (perf_counter_ns() - started_ns) / 1_000_000
    return elapsed_ms, result


def summarize_ms(samples: Sequence[float]) -> LatencyStats | None:
    if not samples:
        return None
    ordered = sorted(samples)
    return LatencyStats(
        count=len(ordered),
        min_ms=ordered[0],
        p50_ms=_percentile(ordered, 0.50),
        p95_ms=_percentile(ordered, 0.95),
        max_ms=ordered[-1],
        mean_ms=mean(ordered),
    )


def format_stats(label: str, stats: LatencyStats) -> str:
    return (
        f"{label}: count={stats.count} "
        f"min={stats.min_ms:.3f}ms p50={stats.p50_ms:.3f}ms "
        f"p95={stats.p95_ms:.3f}ms mean={stats.mean_ms:.3f}ms max={stats.max_ms:.3f}ms"
    )


def _percentile(ordered: Sequence[float], q: float) -> float:
    if len(ordered) == 1:
        return ordered[0]
    rank = (len(ordered) - 1) * q
    low = floor(rank)
    high = ceil(rank)
    if low == high:
        return ordered[low]
    low_val = ordered[low]
    high_val = ordered[high]
    return low_val + (high_val - low_val) * (rank - low)
