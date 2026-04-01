import asyncio
from dataclasses import dataclass
from decimal import Decimal, ROUND_CEILING, ROUND_FLOOR

from .plumbing.types import Fill, Side

@dataclass(frozen=True)
class WorkingQuote:
    px: float
    qty: float
    order_id: str | None = None


@dataclass
class LiveQuoteIDs:
    bid_order_id: str|None = None
    ask_order_id: str|None = None


@dataclass(frozen=True)
class WorkingQuotes:
    bid: WorkingQuote | None = None
    ask: WorkingQuote | None = None


class BinanceMaker:
    def __init__(self, symbol:str, max_rate_per_s:float, *, price_tick: float | None = None):
        self.symbol = symbol
        self.tokens = asyncio.Semaphore(int(max_rate_per_s))  # basic rate control
        self.price_tick = price_tick
        self.live = LiveQuoteIDs()
        self._working = WorkingQuotes()
        self._fills: asyncio.Queue[Fill] = asyncio.Queue()

    async def upsert_quotes(
        self,
        bid: float,
        ask: float,
        size: float | None = None,
        *,
        bid_size: float | None = None,
        ask_size: float | None = None,
    ):
        bid_qty = bid_size if bid_size is not None else size
        ask_qty = ask_size if ask_size is not None else size
        if bid_qty is None or ask_qty is None:
            raise ValueError("Either size or both bid_size and ask_size must be provided.")
        bid, ask = self._normalize_prices(bid, ask)
        async with self.tokens:
            # cancel & replace pattern; venue-specific
            bid_order_id = await self._post_or_replace("buy", bid, bid_qty)
            ask_order_id = await self._post_or_replace("sell", ask, ask_qty)
            self.live.bid_order_id = bid_order_id
            self.live.ask_order_id = ask_order_id
            self._working = WorkingQuotes(
                bid=WorkingQuote(px=bid, qty=bid_qty, order_id=bid_order_id),
                ask=WorkingQuote(px=ask, qty=ask_qty, order_id=ask_order_id),
            )

    async def _post_or_replace(self, side:Side, px:float, qty:float)->str:
        # TODO: implement Binance REST/WS order API
        return "oid123"

    async def next_fill(self)->Fill:
        return await self._fills.get()

    def record_fill(self, fill:Fill)->None:
        self._fills.put_nowait(fill)

    def working_quotes(self) -> WorkingQuotes:
        return self._working

    async def cancel_all(self):
        # cancel live orders
        self.live = LiveQuoteIDs()
        self._working = WorkingQuotes()

    def _normalize_prices(self, bid: float, ask: float) -> tuple[float, float]:
        if self.price_tick is None:
            return bid, ask
        if self.price_tick <= 0:
            raise ValueError("price_tick must be positive.")

        tick = Decimal(str(self.price_tick))
        bid_dec = self._quantize_price(bid, tick, ROUND_FLOOR)
        ask_dec = self._quantize_price(ask, tick, ROUND_CEILING)
        if ask_dec <= bid_dec:
            ask_dec = bid_dec + tick
        return float(bid_dec), float(ask_dec)

    @staticmethod
    def _quantize_price(price: float, tick: Decimal, rounding: str) -> Decimal:
        price_dec = Decimal(str(price))
        ticks = (price_dec / tick).to_integral_value(rounding=rounding)
        return ticks * tick


VenueXMaker = BinanceMaker
