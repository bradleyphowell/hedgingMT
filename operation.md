cross_venue_mm/

  main.py               # async orchestration entrypoint

  
  __init__.py
  config.py
  types.py
  utils.py

  marketdata_y.py       # public trades + L2 book from Y (async stream)
  indicators.py         # microprice, rolling VWAP, rolling vol, depth stats

  quote_engine.py       # fair mid, base spread, risk & inventory adjustments
  venue_x_maker.py      # quoting on X (REST/WS), replace/cancel logic, throttles

  execution_y.py        # hedging on Y (IOC/market + maker ladder)
  hedger.py             # hedge policy: taker %, maker %, slippage caps

  inventory.py          # inventory, limits, reservation-price skew
  risk.py               # controls, kill-switch, stress escalations

  pnl.py                # per-trade PnL, mark-outs, fees, slippage

  wiring.py             # dependency injection / startup


tests/
  test_indicators.py
  test_quote_engine.py
  test_pnl.py