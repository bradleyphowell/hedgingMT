import asyncio
from typing import AsyncIterator, Callable
from .types import BookTop, Trade

class MarketDataY:
    def __init__(self, symbol:str):
        self.symbol = symbol
        self._book: BookTop|None = None
        self._last_trade: Trade|None = None

    async def run(self, on_book:Callable[[BookTop],None], on_trade:Callable[[Trade],None]):
        
        # Pseudocode: connect websocket, subscribe to trades + book
        # await ws.send(subscribe_msg)
        while True:
            msg = await self._recv()  # parse incoming
            if msg["type"]=="book_top":
                self._book = BookTop(**msg["data"])
                on_book(self._book)
            elif msg["type"]=="trade":
                self._last_trade = Trade(**msg["data"])
                on_trade(self._last_trade)

    async def _recv(self): ...
    def last_book(self)->BookTop|None: return self._book
    def last_trade(self)->Trade|None: return self._last_trade
