import argparse
import asyncio
import json
import time
from collections import deque
from dataclasses import asdict
from pathlib import Path
from typing import Any

from aiohttp import WSMsgType, web

from .dashboard_server import resolve_market_selection
from .latency import measure_async_ms, measure_sync_ms, summarize_ms
from .plumbing.config import AppConfig
from .plumbing.types import BookTop, Trade
from .plumbing.wiring import App


STATIC_DIR = Path(__file__).with_name("latency_dashboard")
RATE_WINDOW_MS = 5_000
HISTORY_MAX_SAMPLES = 400

LATENCY_STAGE_SPECS: tuple[dict[str, Any], ...] = (
    {
        "key": "book_event_latency_ms",
        "label": "Book Event -> Local Receive",
        "description": "Exchange depth event time to local receive time, adjusted by Binance server-time clock offset.",
    },
    {
        "key": "book_processing_ms",
        "label": "Book Processing",
        "description": "Local strategy book update time after a book event arrives.",
    },
    {
        "key": "quote_compute_ms",
        "label": "Quote Creation",
        "description": "Time to build a fresh OFI/AS quote plan from the current state.",
    },
    {
        "key": "maker_upsert_ms",
        "label": "Maker Upsert",
        "description": "Local placeholder time to push quotes into the maker adapter.",
    },
    {
        "key": "risk_inventory_check_ms",
        "label": "Risk: Inventory Check",
        "description": "Time spent checking the inventory notional guard before quoting.",
    },
    {
        "key": "risk_market_data_check_ms",
        "label": "Risk: Market Data Check",
        "description": "Time spent checking the market-data staleness guard before quoting.",
    },
    {
        "key": "decision_to_quote_ms",
        "label": "Decision -> Quote Post",
        "description": "End-to-end local path from a received book update through quote creation and maker upsert.",
    },
    {
        "key": "trade_event_latency_ms",
        "label": "Trade Event -> Local Receive",
        "description": "Exchange trade event time to local receive time, adjusted by Binance server-time clock offset.",
    },
    {
        "key": "trade_processing_ms",
        "label": "Trade Processing",
        "description": "Time to update VWAP and realized volatility from a trade event.",
    },
    {
        "key": "order_ack_latency_ms",
        "label": "Order Ack Round Trip",
        "description": "Placeholder until live Binance order placement and exchange acknowledgements are wired.",
        "placeholder": True,
    },
)


def build_latency_rows(
    samples: dict[str, deque[float]],
    last_values: dict[str, float | None],
) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for spec in LATENCY_STAGE_SPECS:
        key = spec["key"]
        if spec.get("placeholder"):
            rows.append(
                {
                    "key": key,
                    "label": spec["label"],
                    "description": spec["description"],
                    "status": "placeholder",
                    "count": 0,
                    "lastMs": None,
                    "minMs": None,
                    "p50Ms": None,
                    "p95Ms": None,
                    "meanMs": None,
                    "maxMs": None,
                }
            )
            continue

        stats = summarize_ms(list(samples.get(key, ())))
        rows.append(
            {
                "key": key,
                "label": spec["label"],
                "description": spec["description"],
                "status": "live" if stats is not None else "idle",
                "count": stats.count if stats is not None else 0,
                "lastMs": last_values.get(key),
                "minMs": stats.min_ms if stats is not None else None,
                "p50Ms": stats.p50_ms if stats is not None else None,
                "p95Ms": stats.p95_ms if stats is not None else None,
                "meanMs": stats.mean_ms if stats is not None else None,
                "maxMs": stats.max_ms if stats is not None else None,
            }
        )
    return rows


def build_latency_summary(
    samples: dict[str, deque[float]],
    *,
    book_rate_per_s: float,
    trade_rate_per_s: float,
    current_book_age_ms: float | None,
    book_queue_depth: int,
    trade_queue_depth: int,
) -> dict[str, Any]:
    def percentile(key: str, attr: str) -> float | None:
        stats = summarize_ms(list(samples.get(key, ())))
        return getattr(stats, attr) if stats is not None else None

    return {
        "bookEventP50Ms": percentile("book_event_latency_ms", "p50_ms"),
        "tradeEventP50Ms": percentile("trade_event_latency_ms", "p50_ms"),
        "bookProcessP95Ms": percentile("book_processing_ms", "p95_ms"),
        "quoteCreateP50Ms": percentile("quote_compute_ms", "p50_ms"),
        "makerUpsertP95Ms": percentile("maker_upsert_ms", "p95_ms"),
        "decisionToQuoteP95Ms": percentile("decision_to_quote_ms", "p95_ms"),
        "bookRatePerSec": book_rate_per_s,
        "tradeRatePerSec": trade_rate_per_s,
        "currentBookAgeMs": current_book_age_ms,
        "bookQueueDepth": book_queue_depth,
        "tradeQueueDepth": trade_queue_depth,
        "orderAckMs": None,
    }


class LatencyDashboardSession:
    def __init__(self, ws: web.WebSocketResponse, default_market: str):
        self.ws = ws
        self.selection = resolve_market_selection(default_market)
        self._state_lock = asyncio.Lock()
        self._app: App | None = None
        self._stream_task: asyncio.Task[None] | None = None
        self._book_worker_task: asyncio.Task[None] | None = None
        self._trade_worker_task: asyncio.Task[None] | None = None
        self._book_queue: asyncio.Queue[BookTop] = asyncio.Queue()
        self._trade_queue: asyncio.Queue[Trade] = asyncio.Queue()
        self._samples: dict[str, deque[float]] = {
            spec["key"]: deque(maxlen=HISTORY_MAX_SAMPLES)
            for spec in LATENCY_STAGE_SPECS
            if not spec.get("placeholder")
        }
        self._last_values: dict[str, float | None] = {}
        self._book_rates: deque[int] = deque()
        self._trade_rates: deque[int] = deque()
        self._clock_offset_ms = 0.0
        self._last_book_recv_ts_ms: int | None = None
        self.state: dict[str, Any] = {}

    async def start(self) -> None:
        await self.switch_market(self.selection.market)

    async def handle_message(self, message: dict[str, Any]) -> None:
        if message.get("type") == "select_market":
            await self.switch_market(message.get("market"))

    async def switch_market(self, raw_market: str | None) -> None:
        await self.close()
        self.selection = resolve_market_selection(raw_market)
        self._app = App(AppConfig(symbol=self.selection.binance_symbol))
        self._clock_offset_ms = await asyncio.to_thread(self._app.market_data.estimate_clock_offset_ms)
        self._samples = {
            spec["key"]: deque(maxlen=HISTORY_MAX_SAMPLES)
            for spec in LATENCY_STAGE_SPECS
            if not spec.get("placeholder")
        }
        self._last_values = {}
        self._book_rates = deque()
        self._trade_rates = deque()
        self._last_book_recv_ts_ms = None
        self._book_queue = asyncio.Queue()
        self._trade_queue = asyncio.Queue()

        async with self._state_lock:
            self.state = self._build_state()
        await self._send_state()

        self._stream_task = asyncio.create_task(
            self._app.market_data.run(on_book=self._enqueue_book, on_trade=self._enqueue_trade)
        )
        self._book_worker_task = asyncio.create_task(self._book_worker())
        self._trade_worker_task = asyncio.create_task(self._trade_worker())

    async def close(self) -> None:
        tasks = [
            task
            for task in (self._stream_task, self._book_worker_task, self._trade_worker_task)
            if task is not None
        ]
        for task in tasks:
            task.cancel()
        for task in tasks:
            try:
                await task
            except asyncio.CancelledError:
                pass
        self._stream_task = None
        self._book_worker_task = None
        self._trade_worker_task = None

    def _enqueue_book(self, book: BookTop) -> None:
        self._book_queue.put_nowait(book)

    def _enqueue_trade(self, trade: Trade) -> None:
        self._trade_queue.put_nowait(trade)

    async def _book_worker(self) -> None:
        while True:
            book = await self._book_queue.get()
            if self._app is None:
                continue

            self._last_book_recv_ts_ms = book.recv_ts_ms or book.ts_ms
            self._record_rate(self._book_rates, self._last_book_recv_ts_ms)
            self._record_sample(
                "book_event_latency_ms",
                _event_latency_ms(book.event_ts_ms, book.recv_ts_ms, self._clock_offset_ms),
            )

            mid_px = (book.bid_px + book.ask_px) / 2
            market_data_age_ms = max(0, _now_ms() - (book.recv_ts_ms or book.ts_ms))
            risk_inventory_ms, _ = measure_sync_ms(self._app.risk.check_inventory, self._app.inventory.qty, mid_px)
            risk_market_data_ms, _ = measure_sync_ms(
                self._app.risk.check_market_data_health,
                market_data_age_ms,
            )
            book_processing_ms, _ = measure_sync_ms(self._app.strategy.on_book, book)
            sigma_bps = self._app.rvol.sigma_bps()
            inv_skew_px = self._app.skew.reservation_skew(sigma_bps, self._app.inventory.qty, mid_px)
            quote_compute_ms, plan = measure_sync_ms(
                self._app.strategy.make_quote_plan,
                book,
                sigma_bps,
                inv_skew_px,
                self._app.cfg.quote.size_usd,
            )
            maker_upsert_ms, _ = await measure_async_ms(
                self._app.maker.upsert_quotes(
                    plan.bid,
                    plan.ask,
                    bid_size=plan.bid_size,
                    ask_size=plan.ask_size,
                )
            )

            decision_to_quote_ms = (
                risk_inventory_ms
                + risk_market_data_ms
                + book_processing_ms
                + quote_compute_ms
                + maker_upsert_ms
            )

            self._record_sample("risk_inventory_check_ms", risk_inventory_ms)
            self._record_sample("risk_market_data_check_ms", risk_market_data_ms)
            self._record_sample("book_processing_ms", book_processing_ms)
            self._record_sample("quote_compute_ms", quote_compute_ms)
            self._record_sample("maker_upsert_ms", maker_upsert_ms)
            self._record_sample("decision_to_quote_ms", decision_to_quote_ms)
            await self._publish_state()

    async def _trade_worker(self) -> None:
        while True:
            trade = await self._trade_queue.get()
            if self._app is None:
                continue

            self._record_rate(self._trade_rates, trade.recv_ts_ms or trade.ts_ms)
            self._record_sample(
                "trade_event_latency_ms",
                _event_latency_ms(trade.event_ts_ms, trade.recv_ts_ms, self._clock_offset_ms),
            )
            trade_processing_ms, _ = measure_sync_ms(self._process_trade, trade)
            self._record_sample("trade_processing_ms", trade_processing_ms)
            await self._publish_state()

    def _process_trade(self, trade: Trade) -> None:
        if self._app is None:
            return
        self._app.vwap.update(trade.px, trade.sz)
        self._app.rvol.update(trade.px)

    def _record_sample(self, key: str, value: float) -> None:
        self._samples[key].append(value)
        self._last_values[key] = value

    def _record_rate(self, store: deque[int], ts_ms: int) -> None:
        store.append(ts_ms)
        cutoff_ts_ms = ts_ms - RATE_WINDOW_MS
        while store and store[0] < cutoff_ts_ms:
            store.popleft()

    def _rate_per_sec(self, store: deque[int]) -> float:
        if not store:
            return 0.0
        if len(store) == 1:
            return 1_000.0 / RATE_WINDOW_MS
        span_ms = max(RATE_WINDOW_MS, store[-1] - store[0])
        return len(store) * 1_000.0 / span_ms

    async def _publish_state(self) -> None:
        async with self._state_lock:
            self.state = self._build_state()
        await self._send_state()

    def _build_state(self) -> dict[str, Any]:
        current_book_age_ms = None
        if self._last_book_recv_ts_ms is not None:
            current_book_age_ms = max(0, _now_ms() - self._last_book_recv_ts_ms)
        return {
            "type": "latency_state",
            "market": asdict(self.selection),
            "clockOffsetMs": self._clock_offset_ms,
            "summary": build_latency_summary(
                self._samples,
                book_rate_per_s=self._rate_per_sec(self._book_rates),
                trade_rate_per_s=self._rate_per_sec(self._trade_rates),
                current_book_age_ms=current_book_age_ms,
                book_queue_depth=self._book_queue.qsize(),
                trade_queue_depth=self._trade_queue.qsize(),
            ),
            "stages": build_latency_rows(self._samples, self._last_values),
            "presets": ["SUI", "BTC", "ETH", "SOL", "DOGE", "ARB"],
            "updatedAtMs": _now_ms(),
        }

    async def _send_state(self) -> None:
        async with self._state_lock:
            payload = json.dumps(self.state)
        await self.ws.send_str(payload)


async def index(_: web.Request) -> web.Response:
    html = (STATIC_DIR / "index.html").read_text(encoding="utf-8")
    html = html.replace("/static/latency.css", f"/static/latency.css?v={_asset_version(STATIC_DIR / 'latency.css')}")
    html = html.replace("/static/latency.js", f"/static/latency.js?v={_asset_version(STATIC_DIR / 'latency.js')}")
    return web.Response(
        text=html,
        content_type="text/html",
        headers={"Cache-Control": "no-store, max-age=0"},
    )


async def websocket_handler(request: web.Request) -> web.WebSocketResponse:
    ws = web.WebSocketResponse(heartbeat=20)
    await ws.prepare(request)

    session = LatencyDashboardSession(ws, default_market=request.app["default_market"])
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
    parser = argparse.ArgumentParser(description="Live latency dashboard for the Binance market-making pipeline.")
    parser.add_argument("--host", default="127.0.0.1", help="Host to bind the dashboard server.")
    parser.add_argument("--port", type=int, default=8090, help="Port to bind the dashboard server.")
    parser.add_argument("--market", default="SUI", help="Default market, e.g. SUI, BTC, ETH.")
    args = parser.parse_args()

    web.run_app(create_app(default_market=args.market), host=args.host, port=args.port)


def _event_latency_ms(event_ts_ms: int | None, recv_ts_ms: int | None, clock_offset_ms: float) -> float:
    if event_ts_ms is None or recv_ts_ms is None:
        return 0.0
    return max(0.0, recv_ts_ms + clock_offset_ms - event_ts_ms)


def _asset_version(path: Path) -> int:
    return int(path.stat().st_mtime_ns)


def _now_ms() -> int:
    return int(time.time() * 1000)


if __name__ == "__main__":
    main()
