from dataclasses import dataclass, field, fields, is_dataclass, replace
from typing import Any


def default_price_tick(symbol: str) -> float | None:
    normalized = symbol.strip().upper()
    if normalized in {"SUI", "SUIUSDT"}:
        return 0.0001
    return None


def _meta(
    *,
    editable: bool = True,
    section: str,
    label: str,
    unit: str = "",
    step: str = "1",
    min_value: float | int | None = None,
    description: str = "",
    nullable: bool = False,
) -> dict[str, Any]:
    return {
        "editable": editable,
        "section": section,
        "label": label,
        "unit": unit,
        "step": step,
        "min": min_value,
        "description": description,
        "nullable": nullable,
    }


@dataclass(frozen=True)
class BinanceFees:
    maker_bps: float = field(
        default=0.0,
        metadata=_meta(
            section="Fees",
            label="Maker Fee",
            unit="bps",
            step="0.1",
            description="Assumed maker fee used in local fill and PnL calculations.",
        ),
    )
    taker_bps: float = field(
        default=4.0,
        metadata=_meta(
            section="Fees",
            label="Taker Fee",
            unit="bps",
            step="0.1",
            description="Taker fee used in the quote engine when estimating spread requirements.",
        ),
    )


@dataclass(frozen=True)
class RiskLimits:
    max_inventory_usd: float = field(
        default=10000.0,
        metadata=_meta(
            section="Risk",
            label="Max Inventory",
            unit="USD",
            step="100",
            min_value=0,
            description="Absolute net inventory notional allowed before quoting is halted.",
        ),
    )
    max_order_rate_per_s: float = field(
        default=5.0,
        metadata=_meta(
            section="Risk",
            label="Max Order Rate",
            unit="orders/s",
            step="0.5",
            min_value=0.1,
            description="Throttle for quote update frequency through the maker adapter.",
        ),
    )
    max_market_data_stale_ms: int = field(
        default=3000,
        metadata=_meta(
            section="Risk",
            label="Max Data Age",
            unit="ms",
            step="100",
            min_value=100,
            description="If the local book is older than this, the app cancels quotes instead of quoting stale data.",
        ),
    )


@dataclass(frozen=True)
class QuoteParams:
    base_refresh_ms: int = field(
        default=250,
        metadata=_meta(
            section="Quoting",
            label="Refresh Interval",
            unit="ms",
            step="25",
            min_value=25,
            description="Target cadence for quote recomputation and upsert.",
        ),
    )
    epsilon_move_bps: float = field(
        default=1.0,
        metadata=_meta(
            section="Quoting",
            label="Move Threshold",
            unit="bps",
            step="0.1",
            min_value=0,
            description="Reserved threshold for move-based refresh logic.",
        ),
    )
    vol_window_secs: int = field(
        default=300,
        metadata=_meta(
            section="Quoting",
            label="Vol Window",
            unit="s",
            step="5",
            min_value=5,
            description="Lookback horizon for realized volatility estimation.",
        ),
    )
    size_usd: float = field(
        default=25000,
        metadata=_meta(
            section="Quoting",
            label="Order Size",
            unit="USD",
            step="100",
            min_value=1,
            description="Per-side quote notional used to convert the model into base-asset size.",
        ),
    )
    size_curve_k: float = field(
        default=1.6,
        metadata=_meta(
            section="Quoting",
            label="Size Curve",
            unit="x",
            step="0.1",
            min_value=0.1,
            description="Convexity factor applied by the quote engine to widen larger clips.",
        ),
    )


@dataclass(frozen=True)
class InventoryParams:
    gamma: float = field(
        default=0.5,
        metadata=_meta(
            section="Inventory",
            label="Gamma",
            unit="x",
            step="0.05",
            min_value=0,
            description="Risk aversion term for reservation-price inventory skew.",
        ),
    )
    horizon_secs: int = field(
        default=300,
        metadata=_meta(
            section="Inventory",
            label="Inventory Horizon",
            unit="s",
            step="5",
            min_value=1,
            description="Time horizon used when translating volatility and inventory into a reservation-price skew.",
        ),
    )


@dataclass(frozen=True)
class OFIParams:
    ofi_window_ms: int = field(
        default=5_000,
        metadata=_meta(
            section="OFI / AS",
            label="OFI Window",
            unit="ms",
            step="100",
            min_value=1,
            description="Rolling time window used to accumulate order flow imbalance.",
        ),
    )
    ofi_trigger: float = field(
        default=0.15,
        metadata=_meta(
            section="OFI / AS",
            label="OFI Trigger",
            unit="norm",
            step="0.01",
            min_value=0,
            description="Absolute normalized OFI level that must be exceeded before the strategy starts leaning.",
        ),
    )
    max_aggression_bps: float = field(
        default=2.0,
        metadata=_meta(
            section="OFI / AS",
            label="Max Aggression",
            unit="bps",
            step="0.1",
            min_value=0,
            description="Maximum inward adjustment on the active side when OFI reaches full strength.",
        ),
    )
    defensive_ratio: float = field(
        default=1.5,
        metadata=_meta(
            section="OFI / AS",
            label="Defensive Ratio",
            unit="x",
            step="0.1",
            min_value=0,
            description="Multiplier applied to the opposite-side widening relative to active-side aggression.",
        ),
    )
    min_quote_gap_bps: float = field(
        default=0.25,
        metadata=_meta(
            section="OFI / AS",
            label="Min Quote Gap",
            unit="bps",
            step="0.05",
            min_value=0,
            description="Hard minimum bid/ask gap enforced after OFI adjustments.",
        ),
    )


@dataclass(frozen=True)
class AppConfig:
    symbol: str = "SUIUSDT"
    exchange: str = "Binance"
    price_tick: float | None = field(
        default=None,
        metadata=_meta(
            section="Venue",
            label="Price Tick",
            unit="px",
            step="0.0001",
            min_value=0,
            description="Price increment enforced by the maker adapter. Leave blank to use the symbol default.",
            nullable=True,
        ),
    )
    fees: BinanceFees = BinanceFees()
    risk: RiskLimits = RiskLimits()
    quote: QuoteParams = QuoteParams()
    inv: InventoryParams = InventoryParams()
    ofi: OFIParams = OFIParams()

    def maker_price_tick(self) -> float | None:
        if self.price_tick is not None:
            return self.price_tick
        return default_price_tick(self.symbol)


def editable_inputs_schema(cfg: AppConfig) -> list[dict[str, Any]]:
    schema: list[dict[str, Any]] = []
    _collect_schema(cfg, prefix=(), schema=schema)
    return schema


def serialize_editable_inputs(cfg: AppConfig) -> dict[str, Any]:
    values: dict[str, Any] = {}
    for item in editable_inputs_schema(cfg):
        values[item["key"]] = _get_nested_value(cfg, tuple(item["path"]))
    return values


def apply_input_overrides(cfg: AppConfig, overrides: dict[str, Any]) -> AppConfig:
    updated = cfg
    allowed = {item["key"]: item for item in editable_inputs_schema(cfg)}
    for key, raw_value in overrides.items():
        if key not in allowed:
            raise ValueError(f"Unknown input '{key}'.")
        item = allowed[key]
        path = tuple(item["path"])
        current_value = _get_nested_value(updated, path)
        coerced = _coerce_value(current_value, raw_value, nullable=bool(item.get("nullable", False)))
        updated = _replace_nested(updated, path, coerced)
    return updated


def _collect_schema(obj: Any, *, prefix: tuple[str, ...], schema: list[dict[str, Any]]) -> None:
    for item in fields(obj):
        value = getattr(obj, item.name)
        path = prefix + (item.name,)
        if is_dataclass(value):
            _collect_schema(value, prefix=path, schema=schema)
            continue
        metadata = item.metadata or {}
        if not metadata.get("editable"):
            continue
        schema.append(
            {
                "key": ".".join(path),
                "path": list(path),
                "section": metadata.get("section", "Inputs"),
                "label": metadata.get("label", item.name),
                "unit": metadata.get("unit", ""),
                "step": metadata.get("step", "1"),
                "min": metadata.get("min"),
                "description": metadata.get("description", ""),
                "nullable": metadata.get("nullable", False),
                "inputType": "number",
            }
        )


def _get_nested_value(obj: Any, path: tuple[str, ...]) -> Any:
    value = obj
    for part in path:
        value = getattr(value, part)
    return value


def _replace_nested(obj: Any, path: tuple[str, ...], value: Any) -> Any:
    if len(path) == 1:
        return replace(obj, **{path[0]: value})
    child = getattr(obj, path[0])
    replaced_child = _replace_nested(child, path[1:], value)
    return replace(obj, **{path[0]: replaced_child})


def _coerce_value(current_value: Any, raw_value: Any, *, nullable: bool) -> Any:
    if raw_value == "":
        if nullable:
            return None
        raise ValueError("Blank values are only allowed for optional inputs.")
    if current_value is None:
        return None if raw_value in (None, "") else float(raw_value)
    if isinstance(current_value, bool):
        return bool(raw_value)
    if isinstance(current_value, int):
        return int(float(raw_value))
    if isinstance(current_value, float):
        return float(raw_value)
    return raw_value
