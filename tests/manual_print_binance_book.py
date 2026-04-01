import argparse
import asyncio
from contextlib import suppress
import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))

from cross_venue_mm.plumbing.config import AppConfig
from cross_venue_mm.plumbing.marketdata_y import BinanceMarketData
from cross_venue_mm.plumbing.types import BookTop


async def main() -> None:
    cfg = AppConfig()
    parser = argparse.ArgumentParser(description="Print top-of-book snapshots from Binance.")
    parser.add_argument("--symbol", default=cfg.symbol, help="Symbol to query, default comes from AppConfig.")
    parser.add_argument("--samples", type=int, default=10, help="Number of book snapshots to print.")
    parser.add_argument("--interval", type=float, default=0.0, help="Optional delay between printed snapshots.")
    parser.add_argument("--timeout", type=float, default=20.0, help="Seconds to wait for each book update.")
    args = parser.parse_args()

    market_data = BinanceMarketData(args.symbol)
    clock_offset_ms = market_data.estimate_clock_offset_ms()
    book_queue: asyncio.Queue[BookTop] = asyncio.Queue()

    def on_book(book: BookTop) -> None:
        book_queue.put_nowait(book)

    stream_task = asyncio.create_task(market_data.run(on_book=on_book, on_trade=lambda _: None))
    try:
        for i in range(args.samples):
            book = await asyncio.wait_for(book_queue.get(), timeout=args.timeout)
            event_latency_ms = None
            if book.event_ts_ms is not None and book.recv_ts_ms is not None:
                event_latency_ms = (book.recv_ts_ms + clock_offset_ms) - book.event_ts_ms
            print(
                f"sample={i+1} symbol={args.symbol} "
                f"bid={book.bid_px} bid_sz={book.bid_sz} "
                f"ask={book.ask_px} ask_sz={book.ask_sz} "
                f"update_id={book.update_id} event_ts_ms={book.event_ts_ms} "
                f"recv_ts_ms={book.recv_ts_ms} clock_offset_ms={clock_offset_ms:.2f} "
                f"event_latency_ms={event_latency_ms:.2f}"
            )
            if i + 1 < args.samples and args.interval > 0:
                await asyncio.sleep(args.interval)
    finally:
        stream_task.cancel()
        with suppress(asyncio.CancelledError):
            await stream_task


if __name__ == "__main__":
    asyncio.run(main())
