from dataclasses import dataclass

from .plumbing.types import Fill


@dataclass(frozen=True)
class FillPnL:
    realized_usd: float
    fee_usd: float
    net_realized_usd: float
    position_qty: float
    average_entry_px: float


@dataclass(frozen=True)
class MarkedPnL:
    realized_usd: float
    fees_usd: float
    unrealized_usd: float
    net_usd: float
    position_qty: float
    average_entry_px: float
    mark_px: float


class PnLTracker:
    def __init__(self) -> None:
        self.position_qty = 0.0
        self.average_entry_px = 0.0
        self.realized_usd = 0.0
        self.fees_usd = 0.0

    def apply_fill(self, fill: Fill, *, fee_bps: float = 0.0) -> FillPnL:
        fee_usd = (fee_bps / 1e4) * fill.px * fill.sz
        realized_usd = 0.0
        signed_qty = fill.sz if fill.side == "buy" else -fill.sz

        if self.position_qty == 0.0 or self.position_qty * signed_qty > 0:
            self._open_position(signed_qty, fill.px)
        else:
            realized_usd = self._close_position(signed_qty, fill.px)

        self.realized_usd += realized_usd
        self.fees_usd += fee_usd
        return FillPnL(
            realized_usd=realized_usd,
            fee_usd=fee_usd,
            net_realized_usd=realized_usd - fee_usd,
            position_qty=self.position_qty,
            average_entry_px=self.average_entry_px,
        )

    def mark_to_market(self, mark_px: float) -> MarkedPnL:
        unrealized_usd = self._unrealized_pnl(mark_px)
        net_usd = self.realized_usd + unrealized_usd - self.fees_usd
        return MarkedPnL(
            realized_usd=self.realized_usd,
            fees_usd=self.fees_usd,
            unrealized_usd=unrealized_usd,
            net_usd=net_usd,
            position_qty=self.position_qty,
            average_entry_px=self.average_entry_px,
            mark_px=mark_px,
        )

    def _open_position(self, signed_qty: float, px: float) -> None:
        if self.position_qty == 0.0:
            self.position_qty = signed_qty
            self.average_entry_px = px
            return

        total_qty = abs(self.position_qty) + abs(signed_qty)
        weighted_notional = (self.average_entry_px * abs(self.position_qty)) + (px * abs(signed_qty))
        self.position_qty += signed_qty
        self.average_entry_px = weighted_notional / total_qty if total_qty else 0.0

    def _close_position(self, signed_qty: float, px: float) -> float:
        existing_qty = self.position_qty
        closing_qty = min(abs(existing_qty), abs(signed_qty))
        remaining_qty = abs(signed_qty) - closing_qty

        if existing_qty > 0:
            realized_usd = (px - self.average_entry_px) * closing_qty
        else:
            realized_usd = (self.average_entry_px - px) * closing_qty

        self.position_qty += signed_qty
        if self.position_qty == 0.0:
            self.average_entry_px = 0.0
        elif existing_qty * self.position_qty < 0 and remaining_qty > 0:
            self.average_entry_px = px
        return realized_usd

    def _unrealized_pnl(self, mark_px: float) -> float:
        if self.position_qty > 0:
            return (mark_px - self.average_entry_px) * self.position_qty
        if self.position_qty < 0:
            return (self.average_entry_px - mark_px) * abs(self.position_qty)
        return 0.0
