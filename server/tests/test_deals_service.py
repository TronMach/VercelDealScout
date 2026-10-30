import asyncio

import httpx
import pytest

from src import deals_service


def deal(appid, name, retail, keyshop):
    return {
        'appid': appid, 'name': name, 'url': '', 'image_url': '', 'currency': 'USD',
        'prices': {'retail_price': retail, 'retail_price_low': 0.0, 'keyshop_price': keyshop, 'keyshop_price_low': 0.0},
    }


def test_best_price_ignores_missing_keyshop_price():
    d = deals_service.add_deal_fields(deal(1, 'A', 9.99, 0.0))
    assert d['best_price'] == 9.99
    assert d['discount'] == 0.0


def test_best_price_takes_cheaper_keyshop():
    d = deals_service.add_deal_fields(deal(1, 'A', 10.0, 2.5))
    assert d['best_price'] == 2.5
    assert d['discount'] == 0.75


def test_keyshop_dearer_than_steam_uses_steam_price():
    d = deals_service.add_deal_fields(deal(1, 'A', 5.0, 8.0))
    assert d['best_price'] == 5.0


def test_sorts():
    deals = [deals_service.add_deal_fields(d) for d in (
        deal(1, 'banana', 10.0, 5.0),   # best 5, 50% off
        deal(2, 'Apple', 4.0, 0.0),     # best 4, 0% off
        deal(3, 'cherry', 20.0, 2.0),   # best 2, 90% off
    )]
    assert [d['appid'] for d in deals_service.sort_deals(deals, 'found')] == [1, 2, 3]
    assert [d['appid'] for d in deals_service.sort_deals(deals, 'price')] == [3, 2, 1]
    assert [d['appid'] for d in deals_service.sort_deals(deals, 'discount')] == [3, 1, 2]
    assert [d['appid'] for d in deals_service.sort_deals(deals, 'name')] == [2, 1, 3]


def test_summary_totals_use_best_price():
    deals = [deals_service.add_deal_fields(d) for d in (deal(1, 'A', 10.0, 5.0), deal(2, 'B', 4.0, 0.0))]
    stats = deals_service.summarize(deals)
    assert stats == {'games_found': 2, 'lowest_deal': 4.0, 'total_retail': 14.0, 'total_deal': 9.0}
    assert deals_service.summarize([])['lowest_deal'] is None


class FakeDealsGG:
    """ Returns one deal per appid, in reverse order like an unordered dict would. """
    def __init__(self, limit_after=None):
        self.calls = 0
        self.limit_after = limit_after

    async def find_products_by_appid(self, appids, max_price):
        self.calls += 1
        if self.limit_after is not None and self.calls > self.limit_after:
            response = httpx.Response(429, request=httpx.Request('GET', 'https://api.gg.deals/'))
            raise httpx.HTTPStatusError('rate limited', request=response.request, response=response)
        return [deal(a, f'game {a}', 10.0, 1.0) for a in reversed(appids)]


def test_fetch_keeps_list_order_across_batches():
    appids = list(range(100, 0, -1))
    deals, limited = asyncio.run(deals_service.fetch_deals(FakeDealsGG(), appids, 10.0))
    assert [d['appid'] for d in deals] == appids
    assert limited is False


def test_fetch_returns_partial_results_when_rate_limited():
    fake = FakeDealsGG(limit_after=1)
    deals, limited = asyncio.run(deals_service.fetch_deals(fake, list(range(90)), 10.0))
    assert limited is True
    assert 0 < len(deals) < 90


def test_fetch_raises_when_every_batch_is_rate_limited():
    with pytest.raises(deals_service.RateLimited):
        asyncio.run(deals_service.fetch_deals(FakeDealsGG(limit_after=0), list(range(60)), 10.0))


def test_unknown_game_from_gg_deals_is_skipped():
    from src.dealsgg_api import DealsGGAPI
    api = DealsGGAPI.__new__(DealsGGAPI)
    response = {'success': True, 'data': {'1': None, '2': {'title': 'B', 'url': '', 'prices': {'currentRetail': '4.99', 'currentKeyshops': '1.00', 'currency': 'USD'}}}}
    assert [d['appid'] for d in api._process_json(response, 10.0)] == [2]
