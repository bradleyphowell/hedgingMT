import asyncio

from cross_venue_mm.plumbing.config import AppConfig
from cross_venue_mm.venue_x_maker import VenueXMaker


def test_venue_x_maker_tracks_working_quotes():
    maker = VenueXMaker("SUI", max_rate_per_s=5)

    asyncio.run(maker.upsert_quotes(100.0, 100.2, bid_size=5.0, ask_size=4.5))
    working = maker.working_quotes()

    assert working.bid is not None
    assert working.ask is not None
    assert working.bid.px == 100.0
    assert working.bid.qty == 5.0
    assert working.ask.px == 100.2
    assert working.ask.qty == 4.5


def test_app_config_defaults_sui_to_four_decimal_tick():
    cfg = AppConfig(symbol="SUIUSDT")

    assert cfg.maker_price_tick() == 0.0001


def test_venue_x_maker_quantizes_prices_to_tick():
    maker = VenueXMaker("SUI", max_rate_per_s=5, price_tick=0.0001)

    asyncio.run(maker.upsert_quotes(0.8804830481941519, 0.8818167280375141, bid_size=5.0, ask_size=4.5))
    working = maker.working_quotes()

    assert working.bid is not None
    assert working.ask is not None
    assert working.bid.px == 0.8804
    assert working.ask.px == 0.8819
