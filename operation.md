cross_venue_mm/

  main.py                     # async Binance-only orchestration entrypoint
  dashboard_server.py         # live Binance dashboard backend
  latency.py                  # latency measurement helpers
  pnl.py                      # single-venue realized + marked PnL
  risk.py                     # inventory and market-data health checks
  venue_x_maker.py            # historical filename; exports BinanceMaker

  model/
    indicators.py             # microprice, VWAP, realized vol
    inventory.py              # inventory state and reservation-price skew
    ofi_avellaneda_stoikov.py # active OFI / AS strategy
    lead_lag_strategy.py      # legacy research model, not the active live path
    quote_engine.py           # base fair-value and spread engine

  plumbing/
    binanceintegration.py     # REST/polling Binance connectivity
    config.py                 # app, fee, quote, and risk config
    marketdata_y.py           # historical filename; exports BinanceMarketData
    types.py                  # shared BookTop / Trade / Fill types
    wiring.py                 # app container assembly

  dashboard/
    index.html
    app.js
    styles.css

tests/
  manual_latency_probe.py
  manual_print_binance_book.py
  test_dashboard_server.py
  test_indicators.py
  test_latency.py
  test_marketdata_y.py
  test_ofi_avellaneda_stoikov.py
  test_pnl.py
  test_quote_engine.py
  test_risk.py
  test_venue_x_maker.py
