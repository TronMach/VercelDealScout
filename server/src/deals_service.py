"""
    Finds deals for a Steam wishlist or library.
    The web app and the Discord commands both call scan(), so they show the same results.
"""
import asyncio
import logging
from typing import Literal

import httpx

from src.dealsgg_api import DealsGGAPI
from src.steam_api import Steam

logger = logging.getLogger(__name__)

Kind = Literal['wishlist', 'library']
SortKey = Literal['found', 'price', 'discount', 'name']
SORT_KEYS: tuple[str, ...] = ('found', 'price', 'discount', 'name')

DEFAULT_MAX_PRICE = 10.00
# GG.deals takes up to 30 appids per request; 15 batches keeps a scan to a few seconds
BATCH_SIZE = 30
MAX_BATCHES = 15
# Requests sent to GG.deals at the same time
CONCURRENCY = 3


class RateLimited(Exception):
    """ GG.deals answered 429 before any batch finished. """


def add_deal_fields(deal: dict) -> dict:
    """
        Adds best_price (cheapest of Steam and keyshop) and discount (0-1, against the Steam price).
        A price of 0.0 means GG.deals has no price, not that the game is free.
    """
    prices = deal['prices']
    retail = prices['retail_price']
    keyshop = prices['keyshop_price']
    best = min(retail, keyshop) if keyshop > 0 else retail
    deal['best_price'] = round(best, 2)
    deal['discount'] = round((retail - best) / retail, 4) if retail > 0 else 0.0
    return deal


def sort_deals(deals: list[dict], sort: SortKey) -> list[dict]:
    """ 'found' keeps the wishlist or library order. Every sort is stable. """
    if sort == 'price':
        return sorted(deals, key=lambda d: d['best_price'])
    if sort == 'discount':
        return sorted(deals, key=lambda d: -d['discount'])
    if sort == 'name':
        return sorted(deals, key=lambda d: d['name'].casefold())
    return list(deals)


def summarize(deals: list[dict]) -> dict:
    best_prices = [d['best_price'] for d in deals if d['best_price'] > 0]
    return {
        'games_found': len(deals),
        'lowest_deal': min(best_prices) if best_prices else None,
        'total_retail': round(sum(d['prices']['retail_price'] for d in deals), 2),
        'total_deal': round(sum(d['best_price'] for d in deals), 2),
    }


async def fetch_deals(dealsgg: DealsGGAPI, appids: list[int], max_price: float) -> tuple[list[dict], bool]:
    """
        Looks up appids on GG.deals in batches.
        Return: deals in appid order, and True if GG.deals rate limited part of the scan.
    """
    batches = [appids[i:i + BATCH_SIZE] for i in range(0, len(appids), BATCH_SIZE)]
    results: list[list[dict] | None] = [None] * len(batches)
    rate_limited = False
    semaphore = asyncio.Semaphore(CONCURRENCY)

    async def run(index: int, batch: list[int]):
        nonlocal rate_limited
        async with semaphore:
            if rate_limited:
                return
            try:
                results[index] = await dealsgg.find_products_by_appid(batch, max_price=max_price) or []
            except httpx.HTTPStatusError as error:
                if error.response.status_code == 429:
                    rate_limited = True
                    return
                raise

    await asyncio.gather(*(run(i, b) for i, b in enumerate(batches)))

    if rate_limited and all(r is None for r in results):
        raise RateLimited()

    # GG.deals returns a dict keyed by appid, so put deals back in wishlist/library order
    order = {appid: i for i, appid in enumerate(appids)}
    deals = [deal for batch in results if batch for deal in batch]
    deals.sort(key=lambda d: order.get(d['appid'], len(order)))
    return deals, rate_limited


async def scan(
    kind: Kind,
    steam_id: str,
    steam: Steam,
    dealsgg: DealsGGAPI,
    max_price: float = DEFAULT_MAX_PRICE,
    sort: SortKey = 'found',
) -> dict:
    """
        Return: {'kind', 'steam_id', 'max_price', 'sort', 'games_total', 'games_scanned',
                 'rate_limited', 'stats', 'deals'}
        Raises: ValueError if the wishlist or library is empty or private, RateLimited, httpx.HTTPError
    """
    items = await (steam.get_wishlist(steam_id) if kind == 'wishlist' else steam.get_library(steam_id))
    appids = [item['appid'] for item in items]
    scanned = appids[:BATCH_SIZE * MAX_BATCHES]

    deals, rate_limited = await fetch_deals(dealsgg, scanned, max_price)
    deals = sort_deals([add_deal_fields(d) for d in deals], sort)

    return {
        'kind': kind,
        'steam_id': steam_id,
        'max_price': max_price,
        'sort': sort,
        'games_total': len(appids),
        'games_scanned': len(scanned),
        'rate_limited': rate_limited,
        'stats': summarize(deals),
        'deals': deals,
    }
