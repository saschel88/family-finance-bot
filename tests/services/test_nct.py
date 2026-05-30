from __future__ import annotations

from bot.services.nct import NctClient


def _client() -> NctClient:
    return NctClient(base_url="https://example.test", cache_ttl=86400)


async def test_lookup_by_gtin_miss_returns_none() -> None:
    client = _client()
    assert await client.lookup_by_gtin("4870000000000") is None


async def test_search_by_name_returns_empty() -> None:
    client = _client()
    assert await client.search_by_name("молоко") == []


async def test_map_category_returns_none() -> None:
    client = _client()
    assert client.map_nct_category_to_local("Молочная продукция") is None


async def test_search_cache_hit_makes_no_http_call() -> None:
    client = _client()
    await client.search_by_name("сыр")
    await client.search_by_name("сыр")
    # The stub never performs HTTP; the cache short-circuits the second call.
    assert client._http_calls == 0
