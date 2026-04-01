from cross_venue_mm.plumbing.config import AppConfig, apply_input_overrides, editable_inputs_schema, serialize_editable_inputs


def test_editable_inputs_schema_includes_quote_and_ofi_controls():
    cfg = AppConfig()
    schema = editable_inputs_schema(cfg)
    keys = {item["key"] for item in schema}

    assert "quote.size_usd" in keys
    assert "ofi.ofi_window_ms" in keys
    assert "risk.max_inventory_usd" in keys


def test_apply_input_overrides_updates_nested_values():
    cfg = AppConfig()

    updated = apply_input_overrides(
        cfg,
        {
            "quote.size_usd": "15000",
            "ofi.ofi_window_ms": "2500",
            "ofi.ofi_trigger": "0.22",
            "price_tick": "",
        },
    )

    assert updated.quote.size_usd == 15000.0
    assert updated.ofi.ofi_window_ms == 2500
    assert updated.ofi.ofi_trigger == 0.22
    assert updated.price_tick is None


def test_serialize_editable_inputs_returns_current_values():
    cfg = AppConfig()
    values = serialize_editable_inputs(cfg)

    assert values["quote.size_usd"] == cfg.quote.size_usd
    assert values["ofi.ofi_window_ms"] == cfg.ofi.ofi_window_ms
