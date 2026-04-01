from dataclasses import dataclass
from math import exp, log

from ..plumbing.types import BookTop, Trade
from .quote_engine import Quote, QuoteEngine


@dataclass(frozen=True)
class LeadLagStrategyParams:
    signal_half_life_ms: int = 1500
    side_impulse_bps: float = 0.35
    activation_bps: float = 0.75
    signal_vol_scale: float = 0.05
    max_signal_bps: float = 6.0
    join_aggression_ratio: float = 0.45
    passive_widen_ratio: float = 0.90
    max_join_bps: float = 2.5
    max_passive_widen_bps: float = 6.0
    active_size_multiplier: float = 1.75
    passive_size_multiplier: float = 0.35
    min_quote_gap_bps: float = 0.25


@dataclass(frozen=True)
class LeadLagQuotePlan:
    bid: float
    ask: float
    bid_size: float
    ask_size: float
    mid_ref: float
    base_half_spread_bps: float
    signal_bps: float
    mode: str


class LeadLagMakerStrategy:
    def __init__(self, quote_engine: QuoteEngine, params: LeadLagStrategyParams | None = None):
        self.quote_engine = quote_engine
        self.params = params or LeadLagStrategyParams()
        self._last_mid_px: float | None = None
        self._last_trade_px: float | None = None
        self._signal_bps: float = 0.0
        self._last_signal_ts_ms: int | None = None

    def on_book(self, book: BookTop) -> None:
        self._last_mid_px = (book.bid_px + book.ask_px) / 2

    def on_trade(self, trade: Trade) -> None:
        ts_ms = trade.event_ts_ms or trade.ts_ms
        signal_bps = self._decayed_signal(ts_ms)

        price_move_bps = 0.0
        if self._last_trade_px is not None and self._last_trade_px > 0 and trade.px > 0:
            price_move_bps = abs(log(trade.px / self._last_trade_px)) * 1e4

        book_gap_bps = 0.0
        if self._last_mid_px is not None and self._last_mid_px > 0:
            book_gap_bps = abs((trade.px - self._last_mid_px) / self._last_mid_px) * 1e4

        shock_bps = min(
            self.params.max_signal_bps,
            self.params.side_impulse_bps + price_move_bps + 0.5 * book_gap_bps,
        )
        direction = 1.0 if trade.side == "buy" else -1.0

        self._signal_bps = self._clamp(
            signal_bps + direction * shock_bps,
            -self.params.max_signal_bps,
            self.params.max_signal_bps,
        )
        self._last_trade_px = trade.px
        self._last_signal_ts_ms = ts_ms

    def on_book_y(self, book: BookTop) -> None:
        self.on_book(book)

    def on_trade_y(self, trade: Trade) -> None:
        self.on_trade(trade)

    def make_quote_plan(
        self,
        book: BookTop,
        sigma_bps: float,
        inv_skew_px: float,
        size_usd: float,
    ) -> LeadLagQuotePlan:
        base_quote = self.quote_engine.compute(book, sigma_bps, inv_skew_px, size_usd=size_usd)
        base_size = size_usd / base_quote.mid_ref

        now_ts_ms = book.event_ts_ms or book.ts_ms
        signal_bps = self._decayed_signal(now_ts_ms)
        activation_bps = max(self.params.activation_bps, sigma_bps * self.params.signal_vol_scale)

        if abs(signal_bps) <= activation_bps:
            return self._neutral_plan(base_quote, base_size, signal_bps)

        strength = min(
            1.0,
            (abs(signal_bps) - activation_bps) / max(1e-9, self.params.max_signal_bps - activation_bps),
        )
        join_bps = min(
            self.params.max_join_bps,
            max(0.0, abs(signal_bps) - activation_bps) * self.params.join_aggression_ratio,
        )
        passive_widen_bps = min(
            self.params.max_passive_widen_bps,
            max(0.0, abs(signal_bps) - activation_bps) * self.params.passive_widen_ratio,
        )

        bid = base_quote.bid
        ask = base_quote.ask
        active_size = base_size * (1.0 + strength * (self.params.active_size_multiplier - 1.0))
        passive_size = base_size * (1.0 - strength * (1.0 - self.params.passive_size_multiplier))

        if signal_bps > 0:
            bid *= 1 + join_bps / 1e4
            ask *= 1 + passive_widen_bps / 1e4
            bid_size = active_size
            ask_size = passive_size
            mode = "buy-lean"
        else:
            bid *= 1 - passive_widen_bps / 1e4
            ask *= 1 - join_bps / 1e4
            bid_size = passive_size
            ask_size = active_size
            mode = "sell-lean"

        bid, ask = self._enforce_min_gap(bid, ask, base_quote.mid_ref)
        return LeadLagQuotePlan(
            bid=bid,
            ask=ask,
            bid_size=bid_size,
            ask_size=ask_size,
            mid_ref=base_quote.mid_ref,
            base_half_spread_bps=base_quote.half_spread_bps,
            signal_bps=signal_bps,
            mode=mode,
        )

    def _neutral_plan(self, base_quote: Quote, base_size: float, signal_bps: float) -> LeadLagQuotePlan:
        return LeadLagQuotePlan(
            bid=base_quote.bid,
            ask=base_quote.ask,
            bid_size=base_size,
            ask_size=base_size,
            mid_ref=base_quote.mid_ref,
            base_half_spread_bps=base_quote.half_spread_bps,
            signal_bps=signal_bps,
            mode="neutral",
        )

    def _decayed_signal(self, now_ts_ms: int) -> float:
        if self._last_signal_ts_ms is None:
            return 0.0
        dt_ms = max(0, now_ts_ms - self._last_signal_ts_ms)
        if self.params.signal_half_life_ms <= 0:
            return self._signal_bps
        decay = exp(-dt_ms * log(2) / self.params.signal_half_life_ms)
        return self._signal_bps * decay

    def _enforce_min_gap(self, bid: float, ask: float, mid_ref: float) -> tuple[float, float]:
        min_gap_px = mid_ref * self.params.min_quote_gap_bps / 1e4
        if ask - bid >= min_gap_px:
            return bid, ask
        center = (bid + ask) / 2
        half_gap = min_gap_px / 2
        return center - half_gap, center + half_gap

    @staticmethod
    def _clamp(value: float, lower: float, upper: float) -> float:
        return max(lower, min(value, upper))
