from collections import deque
from dataclasses import dataclass

from ..plumbing.config import OFIParams
from ..plumbing.types import BookTop
from .quote_engine import Quote, QuoteEngine


class OrderFlowImbalance:
    """Rolling top-of-book OFI signal.

    Units:
    - `window_ms` is a rolling time window in milliseconds.
    - internal OFI terms are in base-asset size units from the book.
    - `value()` returns a depth-normalized score in [-1.0, 1.0].

    Interpretation:
    - positive OFI => bid side is strengthening / ask side is weakening
    - negative OFI => ask side is strengthening / bid side is weakening
    """

    def __init__(self, window_ms: int = 5_000):
        self.window_ms = max(1, window_ms)
        self._last_book: BookTop | None = None
        self._samples: deque[tuple[int, float, float]] = deque()

    def update(self, book: BookTop) -> None:
        sample_ts_ms = book.event_ts_ms or book.ts_ms
        if self._last_book is not None:
            prev = self._last_book
            e_n = 0.0

            # Standard top-of-book OFI increment:
            # - stronger/higher bid contributes positively
            # - stronger/lower ask contributes negatively
            if book.bid_px >= prev.bid_px:
                e_n += book.bid_sz
            if book.bid_px <= prev.bid_px:
                e_n -= prev.bid_sz
            if book.ask_px <= prev.ask_px:
                e_n -= book.ask_sz
            if book.ask_px >= prev.ask_px:
                e_n += prev.ask_sz

            avg_depth = max(1e-9, (book.bid_sz + book.ask_sz + prev.bid_sz + prev.ask_sz) / 4)
            self._samples.append((sample_ts_ms, e_n, avg_depth))
            self._trim(sample_ts_ms)

        self._last_book = book

    def value(self, now_ts_ms: int | None = None) -> float:
        if not self._samples:
            return 0.0
        effective_ts_ms = now_ts_ms
        if effective_ts_ms is None and self._last_book is not None:
            effective_ts_ms = self._last_book.event_ts_ms or self._last_book.ts_ms
        if effective_ts_ms is not None:
            self._trim(effective_ts_ms)
        if not self._samples:
            return 0.0

        total_depth = sum(depth for _, _, depth in self._samples)
        if total_depth <= 0:
            return 0.0
        normalized = sum(ofi_term for _, ofi_term, _ in self._samples) / total_depth
        return max(-1.0, min(1.0, normalized))

    def _trim(self, now_ts_ms: int) -> None:
        cutoff_ts_ms = now_ts_ms - self.window_ms
        while self._samples and self._samples[0][0] < cutoff_ts_ms:
            self._samples.popleft()

@dataclass(frozen=True)
class OFIQuotePlan:
    """Quote plan emitted by the strategy.

    Units:
    - `bid`, `ask`, `mid_ref`: price units of the traded symbol
    - `bid_size`, `ask_size`: base-asset quantity
    - `base_half_spread_bps`: bps
    - `ofi_value`: normalized OFI in [-1, 1]
    """

    bid: float
    ask: float
    bid_size: float
    ask_size: float
    mid_ref: float
    base_half_spread_bps: float
    ofi_value: float
    mode: str


class OFIAvellanedaStoikovStrategy:
    def __init__(self, quote_engine: QuoteEngine, params: OFIParams | None = None):
        self.quote_engine = quote_engine
        self.params = params or OFIParams()
        self.ofi = OrderFlowImbalance(window_ms=self.params.ofi_window_ms)

    def on_book(self, book: BookTop) -> None:
        self.ofi.update(book)

    def on_book_y(self, book: BookTop) -> None:
        self.on_book(book)

    def make_quote_plan(
        self,
        book: BookTop,
        sigma_bps: float,
        inv_skew_px: float,
        size_usd: float,
    ) -> OFIQuotePlan:
        """Build a quote plan from the current book plus OFI state.

        Inputs:
        - `book`: current top of book
        - `sigma_bps`: realized volatility estimate in basis points
        - `inv_skew_px`: reservation-price skew in absolute price units
        - `size_usd`: target quote notional per side in USD
        """
        base_quote = self.quote_engine.compute(book, sigma_bps, inv_skew_px, size_usd=size_usd)
        base_size = size_usd / base_quote.mid_ref  # base-asset quantity
        ofi_value = self.ofi.value(now_ts_ms=book.event_ts_ms or book.ts_ms)

        if abs(ofi_value) < self.params.ofi_trigger:
            return self._neutral_plan(base_quote, base_size, ofi_value)

        # Strength ramps linearly from 0 at the trigger to 1 at OFI magnitude 1.
        strength = min(
            1.0,
            (abs(ofi_value) - self.params.ofi_trigger) / max(1e-9, 1.0 - self.params.ofi_trigger),
        )
        aggressive_bps = strength * self.params.max_aggression_bps
        defensive_bps = aggressive_bps * self.params.defensive_ratio

        bid = base_quote.bid
        ask = base_quote.ask

        if ofi_value > 0:
            # Positive OFI => lean long:
            # pull the bid in and push the ask further away.
            bid *= 1 + aggressive_bps / 1e4
            ask *= 1 + defensive_bps / 1e4
            mode = "buy-lean"
        else:
            # Negative OFI => lean short:
            # push the bid away and pull the ask in.
            bid *= 1 - defensive_bps / 1e4
            ask *= 1 - aggressive_bps / 1e4
            mode = "sell-lean"

        bid, ask = self._enforce_min_gap(bid, ask, base_quote.mid_ref)
        return OFIQuotePlan(
            bid=bid,
            ask=ask,
            bid_size=base_size,
            ask_size=base_size,
            mid_ref=base_quote.mid_ref,
            base_half_spread_bps=base_quote.half_spread_bps,
            ofi_value=ofi_value,
            mode=mode,
        )

    def _neutral_plan(self, base_quote: Quote, base_size: float, ofi_value: float) -> OFIQuotePlan:
        return OFIQuotePlan(
            bid=base_quote.bid,
            ask=base_quote.ask,
            bid_size=base_size,
            ask_size=base_size,
            mid_ref=base_quote.mid_ref,
            base_half_spread_bps=base_quote.half_spread_bps,
            ofi_value=ofi_value,
            mode="neutral",
        )

    def _enforce_min_gap(self, bid: float, ask: float, mid_ref: float) -> tuple[float, float]:
        # Convert the configured minimum spread floor from bps into price units.
        min_gap_px = mid_ref * self.params.min_quote_gap_bps / 1e4
        if ask - bid >= min_gap_px:
            return bid, ask
        center = (bid + ask) / 2
        half_gap = min_gap_px / 2
        return center - half_gap, center + half_gap


OFIAvellanedaStoikovParams = OFIParams
