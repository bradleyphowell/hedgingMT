import asyncio
from .plumbing.types import Side
from dataclasses import dataclass

@dataclass
class LiveQuoteIDs:
    bid_order_id: str|None = None
    ask_order_id: str|None = None

class VenueXMaker:
    def __init__(self, symbol:str, max_rate_per_s:float):
        self.symbol = symbol
        self.tokens = asyncio.Semaphore(int(max_rate_per_s))  # basic rate control
        self.live = LiveQuoteIDs()

    async def upsert_quotes(self, bid:float, ask:float, size:float):
        async with self.tokens:
            # cancel & replace pattern; venue-specific
            self.live.bid_order_id = await self._post_or_replace("buy", bid, size)
            self.live.ask_order_id = await self._post_or_replace("sell", ask, size)

    async def _post_or_replace(self, side:Side, px:float, qty:float)->str:
        # TODO: implement venue X REST/WS order API
        return "oid123"

    async def cancel_all(self):
        # cancel live orders
        ...
