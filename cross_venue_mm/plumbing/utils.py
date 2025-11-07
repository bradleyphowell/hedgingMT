import asyncio
import logging
from datetime import datetime, timezone
from statistics import mean
from typing import Iterable, Optional

# ---------- Time Utilities ----------

def utc_now_ms() -> int:
    """Return current UTC timestamp in milliseconds."""
    return int(datetime.now(timezone.utc).timestamp() * 1000)

def fmt_ts(ms: int) -> str:
    """Format a millisecond timestamp to ISO 8601 string."""
    return datetime.fromtimestamp(ms / 1000, tz=timezone.utc).isoformat()

# ---------- Math / Conversion Utilities ----------

def bps_to_fraction(bps: float) -> float:
    """Convert basis points to decimal fraction."""
    return bps / 1e4

def fraction_to_bps(f: float) -> float:
    """Convert fraction to basis points."""
    return f * 1e4

def safe_mean(values: Iterable[float]) -> Optional[float]:
    """Return mean of iterable or None if empty."""
    vals = list(values)
    return mean(vals) if vals else None

# ---------- Async Rate Limiting ----------

class AsyncRateLimiter:
    """
    Simple async rate limiter using a semaphore and sleep delay.
    Example:
        limiter = AsyncRateLimiter(5, 1.0)  # max 5 ops per second
        async with limiter:
            await do_something()
    """
    def __init__(self, max_calls: int, per_seconds: float):
        self._sem = asyncio.Semaphore(max_calls)
        self._max_calls = max_calls
        self._per_seconds = per_seconds
        asyncio.create_task(self._reset_loop())

    async def _reset_loop(self):
        while True:
            await asyncio.sleep(self._per_seconds)
            for _ in range(self._max_calls - self._sem._value):
                self._sem.release()

    async def __aenter__(self):
        await self._sem.acquire()
        return self

    async def __aexit__(self, exc_type, exc, tb):
        pass

# ---------- Logging Setup ----------

def setup_logger(name: str = "cross_venue_mm", level=logging.INFO) -> logging.Logger:
    """Set up and return a consistent logger across modules."""
    logger = logging.getLogger(name)
    if not logger.handlers:
        handler = logging.StreamHandler()
        formatter = logging.Formatter("[%(asctime)s] %(levelname)s: %(message)s", "%H:%M:%S")
        handler.setFormatter(formatter)
        logger.addHandler(handler)
    logger.setLevel(level)
    return logger