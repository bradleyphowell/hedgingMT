from collections import deque
from math import log, sqrt
from .types import BookTop

class RollingVWAP:
    def __init__(self, n_trades:int=100):
        self.prq = deque(maxlen=n_trades)
        self.vol = 0.0
        self.dol = 0.0
    def update(self, price:float, size:float):
        self.prq.append((price, size))
        self.vol += size; self.dol += price*size
    @property
    def value(self)->float:
        return self.dol / self.vol if self.vol>0 else None

def microprice(book: BookTop) -> float:
    db, da = book.bid_sz, book.ask_sz
    return (book.bid_px*da + book.ask_px*db) / (da+db) if (da+db)>0 else (book.bid_px+book.ask_px)/2

class RollingVol:
    def __init__(self, window_secs:int, step_ms:int=1000):
        self.step_ms = step_ms
        self.window = int(1000*window_secs/step_ms)
        self.returns = deque(maxlen=self.window)
        self.last_px = None
    def update(self, last_trade_px:float):
        if self.last_px is not None and last_trade_px>0:
            self.returns.append(log(last_trade_px/self.last_px))
        self.last_px = last_trade_px
    def sigma_bps(self)->float:
        if not self.returns: return 0.0
        n = len(self.returns); mu = sum(self.returns)/n
        var = sum((r-mu)**2 for r in self.returns)/(max(1,n-1))
        # convert to bps per step, then per second (approx)
        return sqrt(var)*1e4
