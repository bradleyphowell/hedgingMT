import asyncio
import hmac
import hashlib
import time
import json
from dataclasses import dataclass
from typing import Callable, Optional, Dict, Any, Iterable
from urllib.parse import urlencode
from urllib.request import Request, urlopen
from urllib.error import HTTPError, URLError


@dataclass
class BookTop:
    bid_px: float
    bid_sz: float
    ask_px: float
    ask_sz: float
    ts_ms: int


@dataclass
class Trade:
    px: float
    sz: float
    side: str  # "buy" or "sell" (taker side)
    ts_ms: int


@dataclass
class Fill:
    px: float
    sz: float
    side: str  # our perspective; if we sold, side="sell"
    ts_ms: int
    order_id: str


class BinanceAPIError(Exception):
    def __init__(self, status: int, payload: Any):
        super().__init__(f"Binance API error {status}: {payload}")
        self.status = status
        self.payload = payload


class BinanceIntegration:
    """
    Lightweight Binance connectivity using only the Python standard library.

    - Provides market data (best bid/ask and last trade) via polling.
    - Transmits orders (MARKET or LIMIT) via signed REST.
    - Receives fills by polling recent trades and de-duplicating.

    Notes
    - Optimized for low overhead and zero third-party deps.
    - Uses polling (250ms for book/trades; 1s for fills) to avoid websockets.
    - Testnet is supported via binance.vision endpoints.
    """

    def __init__(
        self,
        api_key: Optional[str],
        api_secret: Optional[str],
        symbol: str = "BTCUSDT",
        *,
        testnet: bool = False,
        recv_window_ms: int = 5000,
        user_agent: str = "hedgingMT/1.0",
    ) -> None:
        self.api_key = api_key or ""
        self.api_secret = api_secret or ""
        self.symbol = symbol.upper()
        self.recv_window_ms = recv_window_ms
        self.user_agent = user_agent
        if testnet:
            self._rest_base = "https://testnet.binance.vision"
        else:
            self._rest_base = "https://api.binance.com"

        # last-seen state (to suppress duplicate callbacks)
        self._last_book: Optional[BookTop] = None
        self._last_trade_ts: Optional[int] = None
        self._seen_trade_ids: set[int] = set()  # for fills polling

    # --------------- Public: Market Data ---------------
    async def market_data_loop(
        self,
        on_book: Callable[[BookTop], None],
        on_trade: Callable[[Trade], None],
        *,
        depth_limit: int = 5,
        poll_ms: int = 250,
    ) -> None:
        """Continuously polls top-of-book and recent trade and fires callbacks.

        - on_book receives BookTop on changes.
        - on_trade receives Trade for the latest trade id not yet seen.
        """
        poll_s = max(poll_ms, 50) / 1000.0
        while True:
            try:
                # Fetch book and last trade concurrently using threads.
                book_task = asyncio.to_thread(self._fetch_book_top, depth_limit)
                trade_task = asyncio.to_thread(self._fetch_last_trade)
                book, trade = await asyncio.gather(book_task, trade_task)

                if book is not None and self._book_changed(book):
                    self._last_book = book
                    on_book(book)

                if trade is not None and self._trade_is_new(trade):
                    self._last_trade_ts = trade.ts_ms
                    on_trade(trade)
            except Exception:
                # Swallow errors to keep the loop alive; brief backoff
                await asyncio.sleep(0.5)
            await asyncio.sleep(poll_s)

    def last_book(self) -> Optional[BookTop]:
        return self._last_book

    # --------------- Public: Orders ---------------
    def place_order(
        self,
        side: str,
        quantity: float,
        *,
        price: Optional[float] = None,
        order_type: Optional[str] = None,
        time_in_force: Optional[str] = None,
        client_order_id: Optional[str] = None,
    ) -> Dict[str, Any]:
        """Places an order via REST and returns the raw exchange response.

        - side: "BUY" or "SELL" (case-insensitive accepted)
        - quantity: base-asset quantity
        - price: for LIMIT orders; omit for MARKET
        - order_type: override (default MARKET if no price else LIMIT)
        - time_in_force: e.g., "IOC" for crossing or "GTC" for posting
        - client_order_id: optional client-specified id
        """
        if not self.api_key or not self.api_secret:
            raise ValueError("API key/secret required to place orders")

        side_u = side.upper()
        if side_u not in ("BUY", "SELL"):
            raise ValueError("side must be BUY or SELL")

        params: Dict[str, Any] = {
            "symbol": self.symbol,
            "side": side_u,
            "quantity": self._fmt_num(quantity),
            "newOrderRespType": "FULL",
            "timestamp": self._now_ms(),
            "recvWindow": self.recv_window_ms,
        }

        if price is None and (order_type or "").upper() not in ("LIMIT",):
            params["type"] = (order_type or "MARKET").upper()
        else:
            params["type"] = (order_type or "LIMIT").upper()
            params["price"] = self._fmt_num(price)
            params["timeInForce"] = (time_in_force or "IOC").upper()

        if client_order_id:
            params["newClientOrderId"] = client_order_id

        return self._signed_request("POST", "/api/v3/order", params)

    async def async_place_order(self, *args, **kwargs) -> Dict[str, Any]:
        return await asyncio.to_thread(self.place_order, *args, **kwargs)

    # --------------- Public: Fills ---------------
    async def fills_loop(
        self,
        on_fill: Callable[[Fill], None],
        *,
        poll_interval_s: float = 1.0,
    ) -> None:
        """Continuously polls recent account trades and fires new fills."""
        if not self.api_key or not self.api_secret:
            raise ValueError("API key/secret required for fills polling")

        while True:
            try:
                trades = await asyncio.to_thread(self._fetch_my_trades)
                for t in trades:
                    tid = int(t.get("id"))
                    if tid not in self._seen_trade_ids:
                        self._seen_trade_ids.add(tid)
                        fill = Fill(
                            px=float(t["price"]),
                            sz=float(t["qty"]),
                            side=("buy" if t.get("isBuyer") else "sell"),
                            ts_ms=int(t.get("time", self._now_ms())),
                            order_id=str(t.get("orderId", "")),
                        )
                        on_fill(fill)
            except Exception:
                await asyncio.sleep(0.5)
            await asyncio.sleep(max(0.05, poll_interval_s))

    # --------------- Internal: Market Data fetchers ---------------
    def _fetch_book_top(self, depth_limit: int) -> Optional[BookTop]:
        path = "/api/v3/depth"
        params = {"symbol": self.symbol, "limit": max(5, int(depth_limit))}
        data = self._public_request("GET", path, params)
        bids: Iterable[list] = data.get("bids", [])
        asks: Iterable[list] = data.get("asks", [])
        if not bids or not asks:
            return None
        bid_px, bid_sz = float(bids[0][0]), float(bids[0][1])
        ask_px, ask_sz = float(asks[0][0]), float(asks[0][1])
        return BookTop(bid_px=bid_px, bid_sz=bid_sz, ask_px=ask_px, ask_sz=ask_sz, ts_ms=self._now_ms())

    def _fetch_last_trade(self) -> Optional[Trade]:
        path = "/api/v3/trades"
        params = {"symbol": self.symbol, "limit": 1}
        arr = self._public_request("GET", path, params)
        if not isinstance(arr, list) or not arr:
            return None
        t = arr[-1]
        px = float(t["price"])  # price as string
        sz = float(t["qty"])    # qty as string
        is_buyer_maker = bool(t.get("isBuyerMaker", False))
        # trade stream returns taker side; here isBuyerMaker True => buyer was maker => taker was sell
        side = "sell" if is_buyer_maker else "buy"
        ts_ms = int(t.get("time", self._now_ms()))
        return Trade(px=px, sz=sz, side=side, ts_ms=ts_ms)

    # --------------- Internal: Private fetchers ---------------
    def _fetch_my_trades(self) -> list[Dict[str, Any]]:
        path = "/api/v3/myTrades"
        params = {"symbol": self.symbol, "timestamp": self._now_ms(), "recvWindow": self.recv_window_ms, "limit": 100}
        data = self._signed_request("GET", path, params)
        return data if isinstance(data, list) else []

    # --------------- Internal: HTTP helpers ---------------
    def _public_request(self, method: str, path: str, params: Optional[Dict[str, Any]] = None) -> Any:
        url = self._rest_base + path
        q = urlencode(params or {})
        if method == "GET" and q:
            url = url + ("?" + q)
            body = None
        else:
            body = q.encode() if q else None
        return self._do_request(method, url, body=body, signed=False)

    def _signed_request(self, method: str, path: str, params: Dict[str, Any]) -> Any:
        if not self.api_secret:
            raise ValueError("API secret required for signed requests")
        # ensure timestamp & recvWindow exist
        p = dict(params)
        if "timestamp" not in p:
            p["timestamp"] = self._now_ms()
        if "recvWindow" not in p:
            p["recvWindow"] = self.recv_window_ms

        query = urlencode({k: p[k] for k in sorted(p.keys()) if p[k] is not None})
        sig = hmac.new(self.api_secret.encode(), query.encode(), hashlib.sha256).hexdigest()

        url = self._rest_base + path
        if method == "GET":
            url = url + "?" + query + "&signature=" + sig
            body = None
        else:
            body = (query + "&signature=" + sig).encode()
        return self._do_request(method, url, body=body, signed=True)

    def _do_request(self, method: str, url: str, *, body: Optional[bytes], signed: bool) -> Any:
        headers = {
            "User-Agent": self.user_agent,
            "Content-Type": "application/x-www-form-urlencoded",
        }
        if signed and self.api_key:
            headers["X-MBX-APIKEY"] = self.api_key
        req = Request(url=url, method=method.upper(), data=body, headers=headers)
        try:
            with urlopen(req, timeout=5) as resp:
                raw = resp.read()
                if not raw:
                    return None
                try:
                    return json.loads(raw.decode())
                except json.JSONDecodeError:
                    return raw.decode()
        except HTTPError as e:
            try:
                payload = e.read().decode()
            except Exception:
                payload = str(e)
            raise BinanceAPIError(e.code, payload) from None
        except URLError as e:
            raise ConnectionError(f"Network error: {e}") from None

    # --------------- Internal: utils ---------------
    @staticmethod
    def _fmt_num(x: Optional[float]) -> Optional[str]:
        if x is None:
            return None
        # Binance accepts up to symbol-specific precision; format compactly
        return ("%f" % x).rstrip("0").rstrip(".")

    @staticmethod
    def _now_ms() -> int:
        return int(time.time() * 1000)

    def _book_changed(self, b: BookTop) -> bool:
        lb = self._last_book
        if lb is None:
            return True
        return not (
            b.bid_px == lb.bid_px and b.ask_px == lb.ask_px and b.bid_sz == lb.bid_sz and b.ask_sz == lb.ask_sz
        )

    def _trade_is_new(self, t: Trade) -> bool:
        if self._last_trade_ts is None:
            return True
        return t.ts_ms > self._last_trade_ts
