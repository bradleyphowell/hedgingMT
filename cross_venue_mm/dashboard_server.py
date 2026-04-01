import argparse
import asyncio
import json
import time
from collections import deque
from dataclasses import asdict, dataclass, replace
from pathlib import Path
from typing import Any

from aiohttp import WSMsgType, web
import websockets

from .plumbing.config import AppConfig, apply_input_overrides, editable_inputs_schema, serialize_editable_inputs
from .plumbing.types import BookTop, Trade
from .plumbing.wiring import App
from .venue_x_maker import WorkingQuotes


STATIC_DIR = Path(__file__).with_name("dashboard")


@dataclass(frozen=True)
class MarketSelection:
    market: str
    binance_symbol: str


def resolve_market_selection(raw_market: str | None) -> MarketSelection:
    value = (raw_market or "SUI").strip().upper()
    if not value:
        value = "SUI"
    if value.endswith("USDT"):
        coin = value[:-4]
        binance_symbol = value
    else:
        coin = value
        binance_symbol = f"{coin}USDT"
    return MarketSelection(market=coin, binance_symbol=binance_symbol)


def normalize_binance_depth(payload: dict[str, Any], symbol: str, recv_ts_ms: int) -> dict[str, Any]:
    bids = [{"px": float(px), "sz": float(sz)} for px, sz in payload.get("bids", [])[:10]]
    asks = [{"px": float(px), "sz": float(sz)} for px, sz in payload.get("asks", [])[:10]]
    return _book_payload(
        exchange_key="binance",
        exchange_label="Binance Spot",
        symbol=symbol,
        bids=bids,
        asks=asks,
        recv_ts_ms=recv_ts_ms,
        source_ts_ms=None,
        sequence=payload.get("lastUpdateId"),
    )


def book_top_from_binance_depth(payload: dict[str, Any], recv_ts_ms: int) -> BookTop | None:
    bids = payload.get("bids", [])
    asks = payload.get("asks", [])
    if not bids or not asks:
        return None
    return BookTop(
        bid_px=float(bids[0][0]),
        bid_sz=float(bids[0][1]),
        ask_px=float(asks[0][0]),
        ask_sz=float(asks[0][1]),
        ts_ms=recv_ts_ms,
        update_id=payload.get("lastUpdateId"),
        event_ts_ms=None,
        recv_ts_ms=recv_ts_ms,
    )


def trade_from_binance_trade(payload: dict[str, Any], recv_ts_ms: int) -> Trade:
    trade_ts_ms = int(payload.get("T", recv_ts_ms))
    event_ts_ms = int(payload.get("E", trade_ts_ms))
    return Trade(
        px=float(payload["p"]),
        sz=float(payload["q"]),
        side="sell" if bool(payload.get("m", False)) else "buy",
        ts_ms=trade_ts_ms,
        trade_id=int(payload["t"]),
        event_ts_ms=event_ts_ms,
        recv_ts_ms=recv_ts_ms,
    )

def normalize_working_quotes(
    working_quotes: WorkingQuotes,
    symbol: str,
    mode: str,
    ofi_value: float,
) -> dict[str, Any]:
    bid = None
    ask = None
    quoted_mid_px = None
    quoted_spread_bps = None

    if working_quotes.bid is not None:
        bid = {
            "px": working_quotes.bid.px,
            "sz": working_quotes.bid.qty,
            "orderId": working_quotes.bid.order_id,
        }
    if working_quotes.ask is not None:
        ask = {
            "px": working_quotes.ask.px,
            "sz": working_quotes.ask.qty,
            "orderId": working_quotes.ask.order_id,
        }
    if bid is not None and ask is not None and bid["px"] > 0 and ask["px"] > 0:
        quoted_mid_px = (bid["px"] + ask["px"]) / 2
        quoted_spread_bps = ((ask["px"] - bid["px"]) / quoted_mid_px) * 1e4 if quoted_mid_px else None

    return {
        "label": "Indicative OFI/AS Quotes",
        "symbol": symbol,
        "status": "live",
        "mode": mode,
        "ofiValue": ofi_value,
        "quotedMidPx": quoted_mid_px,
        "quotedSpreadBps": quoted_spread_bps,
        "bid": bid,
        "ask": ask,
        "error": None,
    }


def normalize_account_snapshot(
    app: App,
    working_quotes: WorkingQuotes,
    mark_px: float | None,
) -> dict[str, Any]:
    if mark_px is None or mark_px <= 0:
        return _pending_account(app.cfg.symbol)

    marked = app.pnl.mark_to_market(mark_px)
    exposure_usd = app.risk.inventory_notional_usd(marked.position_qty, mark_px)
    working_bid_usd = (
        working_quotes.bid.px * working_quotes.bid.qty
        if working_quotes.bid is not None
        else 0.0
    )
    working_ask_usd = (
        working_quotes.ask.px * working_quotes.ask.qty
        if working_quotes.ask is not None
        else 0.0
    )

    if marked.position_qty > 0:
        position_side = "long"
    elif marked.position_qty < 0:
        position_side = "short"
    else:
        position_side = "flat"

    return {
        "label": "Live PnL / Exposure",
        "status": "live",
        "positionQty": marked.position_qty,
        "positionSide": position_side,
        "averageEntryPx": marked.average_entry_px if marked.position_qty != 0.0 else None,
        "markPx": marked.mark_px,
        "exposureUsd": exposure_usd,
        "grossExposureUsd": abs(exposure_usd),
        "realizedUsd": marked.realized_usd,
        "unrealizedUsd": marked.unrealized_usd,
        "feesUsd": marked.fees_usd,
        "netUsd": marked.net_usd,
        "workingBidUsd": working_bid_usd,
        "workingAskUsd": working_ask_usd,
        "workingTotalUsd": working_bid_usd + working_ask_usd,
    }


def normalize_public_trade(trade: Trade) -> dict[str, Any]:
    ts_ms = trade.event_ts_ms or trade.ts_ms
    return {
        "tradeId": trade.trade_id,
        "side": trade.side,
        "px": trade.px,
        "sz": trade.sz,
        "tsMs": ts_ms,
    }


def append_public_trade(recent_trades: deque[dict[str, Any]], trade: Trade) -> None:
    recent_trades.appendleft(normalize_public_trade(trade))


def append_price_point(price_history: deque[dict[str, float]], trade: Trade, *, window_ms: int = 10 * 60 * 1000) -> None:
    ts_ms = trade.event_ts_ms or trade.ts_ms
    bucket_ts_ms = ts_ms - (ts_ms % 1000)
    if price_history and price_history[-1]["tsMs"] == bucket_ts_ms:
        price_history[-1]["px"] = trade.px
    else:
        price_history.append({"tsMs": bucket_ts_ms, "px": trade.px})

    cutoff_ts_ms = bucket_ts_ms - window_ms
    while price_history and price_history[0]["tsMs"] < cutoff_ts_ms:
        price_history.popleft()


def make_dashboard_quote_plan(app: App, book: BookTop) -> Any:
    sigma_bps = app.rvol.sigma_bps()
    mid_px = (book.bid_px + book.ask_px) / 2
    inv_skew_px = app.skew.reservation_skew(sigma_bps, app.inventory.qty, mid_px)
    return app.strategy.make_quote_plan(
        book,
        sigma_bps,
        inv_skew_px,
        size_usd=app.cfg.quote.size_usd,
    )


def _book_payload(
    *,
    exchange_key: str,
    exchange_label: str,
    symbol: str,
    bids: list[dict[str, float]],
    asks: list[dict[str, float]],
    recv_ts_ms: int,
    source_ts_ms: int | None,
    sequence: int | None,
) -> dict[str, Any]:
    best_bid = bids[0]["px"] if bids else None
    best_ask = asks[0]["px"] if asks else None
    mid_px = None
    spread_bps = None
    if best_bid is not None and best_ask is not None and best_bid > 0 and best_ask > 0:
        mid_px = (best_bid + best_ask) / 2
        spread_bps = ((best_ask - best_bid) / mid_px) * 1e4 if mid_px else None

    return {
        "exchange": exchange_key,
        "label": exchange_label,
        "symbol": symbol,
        "status": "live",
        "recvTsMs": recv_ts_ms,
        "sourceTsMs": source_ts_ms,
        "sequence": sequence,
        "midPx": mid_px,
        "spreadBps": spread_bps,
        "bids": bids,
        "asks": asks,
        "error": None,
    }


class DashboardSession:
    def __init__(self, ws: web.WebSocketResponse, default_market: str):
        self.ws = ws
        self.default_market = default_market
        self.selection = resolve_market_selection(default_market)
        self._config = AppConfig(symbol=self.selection.binance_symbol)
        self._state_lock = asyncio.Lock()
        self._binance_task: asyncio.Task[None] | None = None
        self._binance_trade_task: asyncio.Task[None] | None = None
        self._last_binance_book: BookTop | None = None
        self._quote_app: App | None = None
        self._book_history: deque[BookTop] = deque()
        self._trade_history: deque[Trade] = deque()
        self._recent_trades: deque[dict[str, Any]] = deque(maxlen=10)
        self._price_history: deque[dict[str, float]] = deque()
        self.state: dict[str, Any] = {}

    async def start(self) -> None:
        await self.switch_market(self.selection.market)

    async def handle_message(self, message: dict[str, Any]) -> None:
        message_type = message.get("type")
        if message_type == "select_market":
            await self.switch_market(message.get("market"))
            return
        if message_type == "update_inputs":
            await self.update_inputs(message.get("values", {}))

    async def switch_market(self, raw_market: str | None) -> None:
        selection = resolve_market_selection(raw_market)
        await self._cancel_streams()
        self.selection = selection
        self._config = replace(self._config, symbol=selection.binance_symbol)
        self._last_binance_book = None
        self._quote_app = App(self._config)
        self._book_history = deque()
        self._trade_history = deque()
        self._recent_trades = deque(maxlen=10)
        self._price_history = deque()
        async with self._state_lock:
            self.state = {
                "type": "state",
                "market": asdict(selection),
                "book": _pending_book("Binance Spot", selection.binance_symbol),
                "myQuotes": _pending_my_quotes(selection.market),
                "account": _pending_account(selection.market),
                "inputs": serialize_editable_inputs(self._config),
                "inputSchema": editable_inputs_schema(self._config),
                "inputError": None,
                "recentTrades": [],
                "priceHistory": [],
                "updatedAtMs": _now_ms(),
                "presets": ["SUI", "BTC", "ETH", "SOL", "DOGE", "ARB"],
            }
        await self._send_state()
        self._binance_task = asyncio.create_task(self._run_binance_stream(selection.binance_symbol))
        self._binance_trade_task = asyncio.create_task(self._run_binance_trade_stream(selection.binance_symbol))

    async def update_inputs(self, values: dict[str, Any]) -> None:
        try:
            self._config = apply_input_overrides(self._config, values)
        except ValueError as exc:
            await self._update_input_state(error=str(exc))
            return

        self._quote_app = self._rebuild_quote_app()
        await self._update_input_state(
            inputs=serialize_editable_inputs(self._config),
            schema=editable_inputs_schema(self._config),
            error=None,
        )
        if self._last_binance_book is not None:
            await self._refresh_working_quotes(self._last_binance_book)

    async def close(self) -> None:
        await self._cancel_streams()

    async def _cancel_streams(self) -> None:
        tasks = [task for task in (self._binance_task, self._binance_trade_task) if task is not None]
        for task in tasks:
            task.cancel()
        for task in tasks:
            try:
                await task
            except asyncio.CancelledError:
                pass
        self._binance_task = None
        self._binance_trade_task = None

    async def _run_binance_stream(self, symbol: str) -> None:
        url = f"wss://data-stream.binance.vision/ws/{symbol.lower()}@depth10@100ms"
        while True:
            try:
                await self._update_book_status(status="connecting", error=None)
                async with websockets.connect(url, ping_interval=20, ping_timeout=60) as websocket:
                    async for raw_message in websocket:
                        recv_ts_ms = _now_ms()
                        payload = json.loads(raw_message)
                        snapshot = normalize_binance_depth(payload, symbol, recv_ts_ms)
                        await self._update_book(snapshot)
                        book = book_top_from_binance_depth(payload, recv_ts_ms)
                        if book is not None:
                            await self._update_quote_book(book)
            except asyncio.CancelledError:
                raise
            except Exception as exc:
                await self._update_book_status(status="reconnecting", error=str(exc))
                await asyncio.sleep(1.0)

    async def _run_binance_trade_stream(self, symbol: str) -> None:
        url = f"wss://data-stream.binance.vision/ws/{symbol.lower()}@trade"
        while True:
            try:
                async with websockets.connect(url, ping_interval=20, ping_timeout=60) as websocket:
                    async for raw_message in websocket:
                        recv_ts_ms = _now_ms()
                        payload = json.loads(raw_message)
                        trade = trade_from_binance_trade(payload, recv_ts_ms)
                        await self._update_quote_trade(trade)
            except asyncio.CancelledError:
                raise
            except Exception:
                await asyncio.sleep(1.0)

    async def _update_quote_book(self, book: BookTop) -> None:
        if self._quote_app is None:
            return
        self._last_binance_book = book
        self._book_history.append(book)
        self._trim_book_history(book)
        self._quote_app.strategy.on_book(book)
        await self._refresh_working_quotes(book)

    async def _update_quote_trade(self, trade: Trade) -> None:
        if self._quote_app is None:
            return
        self._trade_history.append(trade)
        self._trim_trade_history(trade)
        self._quote_app.vwap.update(trade.px, trade.sz)
        self._quote_app.rvol.update(trade.px)
        await self._record_public_trade(trade)
        if self._last_binance_book is not None:
            await self._refresh_working_quotes(self._last_binance_book)

    async def _refresh_working_quotes(self, book: BookTop) -> None:
        if self._quote_app is None:
            return
        plan = make_dashboard_quote_plan(self._quote_app, book)
        await self._quote_app.maker.upsert_quotes(
            plan.bid,
            plan.ask,
            bid_size=plan.bid_size,
            ask_size=plan.ask_size,
        )
        snapshot = normalize_working_quotes(
            self._quote_app.maker.working_quotes(),
            symbol=self.selection.market,
            mode=plan.mode,
            ofi_value=self._quote_app.strategy.ofi.value(),
        )
        mark_px = (book.bid_px + book.ask_px) / 2
        account = normalize_account_snapshot(
            self._quote_app,
            self._quote_app.maker.working_quotes(),
            mark_px,
        )
        await self._update_strategy_state(snapshot, account)

    async def _record_public_trade(self, trade: Trade) -> None:
        append_public_trade(self._recent_trades, trade)
        append_price_point(self._price_history, trade)
        async with self._state_lock:
            if self.state.get("market", {}).get("market") != self.selection.market:
                return
            self.state["recentTrades"] = list(self._recent_trades)
            self.state["priceHistory"] = list(self._price_history)
            self.state["updatedAtMs"] = _now_ms()
        await self._send_state()

    async def _update_book(self, snapshot: dict[str, Any]) -> None:
        async with self._state_lock:
            if self.state.get("market", {}).get("market") != self.selection.market:
                return
            self.state["book"] = snapshot
            self.state["updatedAtMs"] = _now_ms()
        await self._send_state()

    async def _update_book_status(self, *, status: str, error: str | None) -> None:
        async with self._state_lock:
            book = self.state["book"]
            book["status"] = status
            book["error"] = error
            book["recvTsMs"] = _now_ms()
            self.state["updatedAtMs"] = _now_ms()
        await self._send_state()

    async def _update_strategy_state(self, my_quotes: dict[str, Any], account: dict[str, Any]) -> None:
        async with self._state_lock:
            if self.state.get("market", {}).get("market") != self.selection.market:
                return
            self.state["myQuotes"] = my_quotes
            self.state["account"] = account
            self.state["updatedAtMs"] = _now_ms()
        await self._send_state()

    async def _send_state(self) -> None:
        async with self._state_lock:
            payload = json.dumps(self.state)
        await self.ws.send_str(payload)

    async def _update_input_state(
        self,
        *,
        inputs: dict[str, Any] | None = None,
        schema: list[dict[str, Any]] | None = None,
        error: str | None,
    ) -> None:
        async with self._state_lock:
            if inputs is not None:
                self.state["inputs"] = inputs
            if schema is not None:
                self.state["inputSchema"] = schema
            self.state["inputError"] = error
            self.state["updatedAtMs"] = _now_ms()
        await self._send_state()

    def _rebuild_quote_app(self) -> App:
        previous_app = self._quote_app
        rebuilt = App(self._config)
        if previous_app is not None:
            rebuilt.inventory = previous_app.inventory
            rebuilt.pnl = previous_app.pnl
        for trade in self._trade_history:
            rebuilt.vwap.update(trade.px, trade.sz)
            rebuilt.rvol.update(trade.px)
        for book in self._book_history:
            rebuilt.strategy.on_book(book)
        return rebuilt

    def _trim_book_history(self, latest_book: BookTop) -> None:
        latest_ts_ms = latest_book.event_ts_ms or latest_book.ts_ms
        cutoff_ts_ms = latest_ts_ms - 60 * 60 * 1000
        while self._book_history and (self._book_history[0].event_ts_ms or self._book_history[0].ts_ms) < cutoff_ts_ms:
            self._book_history.popleft()

    def _trim_trade_history(self, latest_trade: Trade) -> None:
        latest_ts_ms = latest_trade.event_ts_ms or latest_trade.ts_ms
        cutoff_ts_ms = latest_ts_ms - 60 * 60 * 1000
        while self._trade_history and (self._trade_history[0].event_ts_ms or self._trade_history[0].ts_ms) < cutoff_ts_ms:
            self._trade_history.popleft()


def _pending_book(label: str, symbol: str) -> dict[str, Any]:
    return {
        "label": label,
        "symbol": symbol,
        "status": "idle",
        "recvTsMs": None,
        "sourceTsMs": None,
        "sequence": None,
        "midPx": None,
        "spreadBps": None,
        "bids": [],
        "asks": [],
        "error": None,
    }


def _pending_my_quotes(symbol: str) -> dict[str, Any]:
    return {
        "label": "Indicative OFI/AS Quotes",
        "symbol": symbol,
        "status": "idle",
        "mode": "idle",
        "ofiValue": None,
        "quotedMidPx": None,
        "quotedSpreadBps": None,
        "bid": None,
        "ask": None,
        "error": None,
    }


def _pending_account(symbol: str) -> dict[str, Any]:
    return {
        "label": "Live PnL / Exposure",
        "symbol": symbol,
        "status": "idle",
        "positionQty": 0.0,
        "positionSide": "flat",
        "averageEntryPx": None,
        "markPx": None,
        "exposureUsd": 0.0,
        "grossExposureUsd": 0.0,
        "realizedUsd": 0.0,
        "unrealizedUsd": 0.0,
        "feesUsd": 0.0,
        "netUsd": 0.0,
        "workingBidUsd": 0.0,
        "workingAskUsd": 0.0,
        "workingTotalUsd": 0.0,
    }


def _now_ms() -> int:
    return int(time.time() * 1000)


def _asset_version(path: Path) -> int:
    return int(path.stat().st_mtime_ns)


async def index(_: web.Request) -> web.Response:
    html = (STATIC_DIR / "index.html").read_text(encoding="utf-8")
    html = html.replace("/static/styles.css", f"/static/styles.css?v={_asset_version(STATIC_DIR / 'styles.css')}")
    html = html.replace("/static/app.js", f"/static/app.js?v={_asset_version(STATIC_DIR / 'app.js')}")
    return web.Response(
        text=html,
        content_type="text/html",
        headers={"Cache-Control": "no-store, max-age=0"},
    )


async def websocket_handler(request: web.Request) -> web.WebSocketResponse:
    ws = web.WebSocketResponse(heartbeat=20)
    await ws.prepare(request)

    session = DashboardSession(ws, default_market=request.app["default_market"])
    await session.start()

    try:
        async for msg in ws:
            if msg.type == WSMsgType.TEXT:
                try:
                    payload = json.loads(msg.data)
                except json.JSONDecodeError:
                    continue
                await session.handle_message(payload)
            elif msg.type == WSMsgType.ERROR:
                break
    finally:
        await session.close()

    return ws


def create_app(default_market: str = "SUI") -> web.Application:
    app = web.Application()
    app["default_market"] = default_market
    app.router.add_get("/", index)
    app.router.add_get("/ws", websocket_handler)
    app.router.add_static("/static/", path=str(STATIC_DIR), show_index=False)
    return app


def main() -> None:
    parser = argparse.ArgumentParser(description="Live Binance OFI/AS dashboard.")
    parser.add_argument("--host", default="127.0.0.1", help="Host to bind the dashboard server.")
    parser.add_argument("--port", type=int, default=8080, help="Port to bind the dashboard server.")
    parser.add_argument("--market", default="SUI", help="Default market, e.g. SUI, BTC, ETH.")
    args = parser.parse_args()

    web.run_app(create_app(default_market=args.market), host=args.host, port=args.port)


if __name__ == "__main__":
    main()
