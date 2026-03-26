import asyncio
import json
import time
from dataclasses import dataclass
from typing import Any, Callable
from urllib.parse import urlencode
from urllib.request import Request, urlopen

import websockets

from .types import BookTop, Trade


@dataclass(frozen=True)
class DepthEvent:
    first_update_id: int
    final_update_id: int
    bids: list[tuple[float, float]]
    asks: list[tuple[float, float]]
    event_ts_ms: int
    recv_ts_ms: int


class MarketDataY:
    def __init__(self, symbol: str, *, testnet: bool = False):
        self.symbol = symbol.upper()
        self._stream_symbol = self.symbol.lower()
        self._book: BookTop | None = None
        self._last_trade: Trade | None = None
        self._last_trade_id: int | None = None
        self._last_update_id: int | None = None
        self._bids: dict[float, float] = {}
        self._asks: dict[float, float] = {}
        self._user_agent = "hedgingMT/1.0"
        if testnet:
            self._rest_base = "https://testnet.binance.vision"
            self._ws_base = "wss://stream.testnet.binance.vision"
        else:
            self._rest_base = "https://api.binance.com"
            self._ws_base = "wss://data-stream.binance.vision"

    async def run(self, on_book: Callable[[BookTop], None], on_trade: Callable[[Trade], None]):
        while True:
            try:
                await self._run_once(on_book=on_book, on_trade=on_trade)
            except asyncio.CancelledError:
                raise
            except Exception:
                self._reset_depth_state()
                await asyncio.sleep(1.0)

    async def _run_once(self, on_book: Callable[[BookTop], None], on_trade: Callable[[Trade], None]) -> None:
        stream_path = (
            f"/stream?streams={self._stream_symbol}@trade/{self._stream_symbol}@depth@100ms"
        )
        buffered_depth_events: list[DepthEvent] = []
        snapshot_task: asyncio.Task[dict[str, Any]] | None = None

        async with websockets.connect(
            self._ws_base + stream_path,
            ping_interval=20,
            ping_timeout=60,
            max_queue=4096,
        ) as websocket:
            async for raw_message in websocket:
                recv_ts_ms = self._now_ms()
                message = json.loads(raw_message)
                data = message.get("data", message)
                event_type = data.get("e")

                if event_type == "trade":
                    trade = self._parse_trade_event(data, recv_ts_ms)
                    if self._trade_is_new(trade):
                        self._last_trade = trade
                        self._last_trade_id = trade.trade_id
                        on_trade(trade)
                    continue

                if event_type != "depthUpdate":
                    continue

                depth_event = self._parse_depth_event(data, recv_ts_ms)
                if self._last_update_id is None:
                    buffered_depth_events.append(depth_event)
                    if snapshot_task is None:
                        snapshot_task = asyncio.create_task(
                            asyncio.to_thread(self._fetch_depth_snapshot, 5000)
                        )
                    if snapshot_task.done():
                        snapshot = snapshot_task.result()
                        while buffered_depth_events and int(snapshot["lastUpdateId"]) < buffered_depth_events[0].first_update_id:
                            snapshot = await asyncio.to_thread(self._fetch_depth_snapshot, 5000)
                        for book in self._initialize_from_snapshot(snapshot, buffered_depth_events):
                            on_book(book)
                        buffered_depth_events.clear()
                        snapshot_task = None
                    continue

                if not self._apply_depth_event(depth_event):
                    raise RuntimeError("Missed a depth update; reconnecting to resync venue Y order book.")
                book = self._build_book_top(
                    event_ts_ms=depth_event.event_ts_ms,
                    recv_ts_ms=depth_event.recv_ts_ms,
                    update_id=depth_event.final_update_id,
                )
                if book is not None and self._book_changed(book):
                    self._book = book
                    on_book(book)

    def _initialize_from_snapshot(
        self,
        snapshot: dict[str, Any],
        buffered_depth_events: list[DepthEvent],
    ) -> list[BookTop]:
        self._load_snapshot(snapshot)
        relevant_events = [
            event for event in buffered_depth_events if event.final_update_id > self._last_update_id
        ]
        if relevant_events and relevant_events[0].first_update_id > self._last_update_id + 1:
            raise RuntimeError("Buffered depth events do not bridge the venue Y snapshot.")

        books: list[BookTop] = []
        for event in relevant_events:
            if not self._apply_depth_event(event):
                raise RuntimeError("Depth event gap encountered while initializing venue Y order book.")
            book = self._build_book_top(
                event_ts_ms=event.event_ts_ms,
                recv_ts_ms=event.recv_ts_ms,
                update_id=event.final_update_id,
            )
            if book is not None and self._book_changed(book):
                self._book = book
                books.append(book)
        return books

    def _load_snapshot(self, snapshot: dict[str, Any]) -> None:
        self._bids = {
            float(price): float(size)
            for price, size in snapshot.get("bids", [])
            if float(size) > 0.0
        }
        self._asks = {
            float(price): float(size)
            for price, size in snapshot.get("asks", [])
            if float(size) > 0.0
        }
        self._last_update_id = int(snapshot["lastUpdateId"])

    def _apply_depth_event(self, event: DepthEvent) -> bool:
        if self._last_update_id is None:
            return False
        if event.final_update_id <= self._last_update_id:
            return True
        if event.first_update_id > self._last_update_id + 1:
            return False

        for price, size in event.bids:
            if size == 0.0:
                self._bids.pop(price, None)
            else:
                self._bids[price] = size
        for price, size in event.asks:
            if size == 0.0:
                self._asks.pop(price, None)
            else:
                self._asks[price] = size

        self._last_update_id = event.final_update_id
        return True

    def _build_book_top(self, event_ts_ms: int, recv_ts_ms: int, update_id: int) -> BookTop | None:
        if not self._bids or not self._asks:
            return None
        bid_px = max(self._bids)
        ask_px = min(self._asks)
        return BookTop(
            bid_px=bid_px,
            bid_sz=self._bids[bid_px],
            ask_px=ask_px,
            ask_sz=self._asks[ask_px],
            ts_ms=event_ts_ms,
            update_id=update_id,
            event_ts_ms=event_ts_ms,
            recv_ts_ms=recv_ts_ms,
        )

    def _parse_trade_event(self, data: dict[str, Any], recv_ts_ms: int) -> Trade:
        trade_ts_ms = int(data["T"])
        event_ts_ms = int(data.get("E", trade_ts_ms))
        return Trade(
            px=float(data["p"]),
            sz=float(data["q"]),
            side="sell" if bool(data.get("m", False)) else "buy",
            ts_ms=trade_ts_ms,
            trade_id=int(data["t"]),
            event_ts_ms=event_ts_ms,
            recv_ts_ms=recv_ts_ms,
        )

    def _parse_depth_event(self, data: dict[str, Any], recv_ts_ms: int) -> DepthEvent:
        return DepthEvent(
            first_update_id=int(data["U"]),
            final_update_id=int(data["u"]),
            bids=[(float(price), float(size)) for price, size in data.get("b", [])],
            asks=[(float(price), float(size)) for price, size in data.get("a", [])],
            event_ts_ms=int(data["E"]),
            recv_ts_ms=recv_ts_ms,
        )

    def _trade_is_new(self, trade: Trade) -> bool:
        if trade.trade_id is None:
            return self._last_trade is None or trade.ts_ms > self._last_trade.ts_ms
        return self._last_trade_id is None or trade.trade_id > self._last_trade_id

    def _fetch_depth_snapshot(self, limit: int) -> dict[str, Any]:
        params = urlencode({"symbol": self.symbol, "limit": limit})
        return self._get_json(f"{self._rest_base}/api/v3/depth?{params}")

    def estimate_clock_offset_ms(self, samples: int = 5) -> float:
        best_offset_ms = 0.0
        best_rtt_ms = float("inf")
        for _ in range(max(1, samples)):
            local_start_ms = time.time() * 1000
            server_time = float(self._get_json(f"{self._rest_base}/api/v3/time")["serverTime"])
            local_end_ms = time.time() * 1000
            rtt_ms = local_end_ms - local_start_ms
            midpoint_ms = local_start_ms + rtt_ms / 2
            offset_ms = server_time - midpoint_ms
            if rtt_ms < best_rtt_ms:
                best_rtt_ms = rtt_ms
                best_offset_ms = offset_ms
        return best_offset_ms

    def _get_json(self, url: str) -> dict[str, Any]:
        request = Request(
            url=url,
            method="GET",
            headers={"User-Agent": self._user_agent},
        )
        with urlopen(request, timeout=5) as response:
            return json.loads(response.read().decode())

    def _book_changed(self, book: BookTop) -> bool:
        if self._book is None:
            return True
        return not (
            book.bid_px == self._book.bid_px
            and book.bid_sz == self._book.bid_sz
            and book.ask_px == self._book.ask_px
            and book.ask_sz == self._book.ask_sz
        )

    def _reset_depth_state(self) -> None:
        self._last_update_id = None
        self._bids = {}
        self._asks = {}

    @staticmethod
    def _now_ms() -> int:
        return int(time.time() * 1000)

    def last_book(self) -> BookTop | None:
        return self._book

    def last_trade(self) -> Trade | None:
        return self._last_trade
