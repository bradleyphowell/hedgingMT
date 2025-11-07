from .plumbing.config import AppConfig
from .plumbing.types import Side
from .execution_y import ExecutionY, ExecReport

class Hedger:
    def __init__(self, cfg:AppConfig, exec_y:ExecutionY):
        self.cfg = cfg
        self.exec = exec_y

    async def hedge_fill(self, side_on_x:Side, qty:float, ref_px:float)->list[ExecReport]:
        # if we sold on X, we must buy on Y; if we bought on X, we must sell on Y
        hedge_side = "buy" if side_on_x=="sell" else "sell"
        taker_qty = qty * self.cfg.hedge.taker_fraction
        maker_qty = qty - taker_qty
        reports = []

        if taker_qty > 0:
            rep = await self.exec.ioc_cross(
                side=hedge_side,
                qty=taker_qty,
                ref_px=ref_px,
                max_slippage_bps=self.cfg.hedge.max_slippage_bps
            )
            reports.append(rep)

        if maker_qty > 0:
            # post around micro +/- bps
            post_px = ref_px * (1 - self.cfg.hedge.post_bps_from_micro/1e4 if hedge_side=="buy"
                                else 1 + self.cfg.hedge.post_bps_from_micro/1e4)
            rep = await self.exec.post_maker(hedge_side, maker_qty, post_px)  # type: ignore
            reports.append(rep)

        return reports
