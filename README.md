# hedgingMT

`hedgingMT` is now a single-venue Binance market-making project.

The active strategy path is an OFI-driven Avellaneda-Stoikov style quoting model. Public market data, indicative quotes, latency tooling, PnL accounting, and risk checks are all centered on Binance. The package name `cross_venue_mm` is historical, but the active code path is no longer cross-exchange.

## Current scope

- Binance websocket market data for public trades and top-of-book
- OFI / AS indicative quoting
- Single-venue inventory, realized PnL, and mark-to-market PnL tracking
- Inventory and market-data health risk checks
- Manual latency benchmarking tools
- Browser dashboard for one Binance market

## Main modules

- [main.py](c:/Users/bradl/trading/hedgingMT/cross_venue_mm/main.py)
  Async Binance-only orchestration loop.
- [wiring.py](c:/Users/bradl/trading/hedgingMT/cross_venue_mm/plumbing/wiring.py)
  Builds the app container, strategy, market data, maker adapter, PnL tracker, risk manager, and Binance integration.
- [marketdata_y.py](c:/Users/bradl/trading/hedgingMT/cross_venue_mm/plumbing/marketdata_y.py)
  Historical filename, but it now exports `BinanceMarketData`.
- [venue_x_maker.py](c:/Users/bradl/trading/hedgingMT/cross_venue_mm/venue_x_maker.py)
  Historical filename, but it now exports `BinanceMaker`.
- [binanceintegration.py](c:/Users/bradl/trading/hedgingMT/cross_venue_mm/plumbing/binanceintegration.py)
  REST/polling Binance connectivity for market data, orders, and fills.
- [ofi_avellaneda_stoikov.py](c:/Users/bradl/trading/hedgingMT/cross_venue_mm/model/ofi_avellaneda_stoikov.py)
  Active single-venue quote model.
- [pnl.py](c:/Users/bradl/trading/hedgingMT/cross_venue_mm/pnl.py)
  Single-venue fill accounting and mark-to-market PnL.
- [risk.py](c:/Users/bradl/trading/hedgingMT/cross_venue_mm/risk.py)
  Inventory notional and market-data staleness checks.
- [dashboard_server.py](c:/Users/bradl/trading/hedgingMT/cross_venue_mm/dashboard_server.py)
  Live dashboard backend.

## Run the dashboard

```powershell
python -m cross_venue_mm.dashboard_server --host 127.0.0.1 --port 8080 --market SUI
```

Open `http://127.0.0.1:8080`.

The dashboard shows:

- Binance ladder, 10 levels deep
- Indicative OFI/AS quotes
- Current OFI
- Recent public trades
- Rolling 10-minute price chart

## Manual tools

Print live Binance top of book:

```powershell
python tests\manual_print_binance_book.py --symbol SUIUSDT --samples 10 --timeout 20
```

Run the single-venue latency probe:

```powershell
python tests\manual_latency_probe.py --symbol SUIUSDT --samples 10 --timeout 20
```

The latency probe measures:

- Binance book event latency
- Binance trade event latency
- Quote computation time
- Maker upsert time
- Fill queue handoff
- PnL update time
- Risk check time

## Tests

There is no `pytest` dependency installed in this workspace by default, so the project is usually verified with:

```powershell
python -m compileall cross_venue_mm tests
```

Targeted test functions can also be executed directly from the `tests/` modules.

## Current limitations

- `BinanceMaker` is still a local stub for quote storage and synthetic fills; it does not yet submit live cancel-replace orders.
- `BinanceIntegration` exists for signed REST order placement and fill polling, but it is not yet wired into the quoting loop.
- The repo still contains some historical filenames from the old cross-venue layout, but the active runtime path is Binance-only.

## Next steps

- Wire `BinanceMaker` into live Binance order placement and cancel-replace logic
- Replace synthetic fill handling with Binance user-data or account-trade ingestion
- Add backtesting and replay tooling for OFI/AS calibration
- Persist PnL, inventory, and risk snapshots for monitoring
