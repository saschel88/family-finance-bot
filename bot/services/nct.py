from __future__ import annotations

import time

from bot.core.logging import get_logger
from bot.services.schemas import NctProduct

logger = get_logger(__name__)


class NctClient:
    """National Catalog client — STUB implementation.

    The full interface and an in-memory TTL cache are present so the real
    HTTP client can drop in later without touching callers. Every method
    currently logs a structured "stub" event and falls through gracefully
    (empty / None), per the project's NCT integration policy.
    """

    def __init__(
        self,
        base_url: str,
        api_key: str | None = None,
        cache_ttl: int = 86400,
    ) -> None:
        self._base_url = base_url
        self._api_key = api_key
        self._cache_ttl = cache_ttl
        self._cache: dict[str, tuple[float, object]] = {}
        self._http_calls = 0

    def _cache_get(self, key: str) -> object | None:
        entry = self._cache.get(key)
        if entry is None:
            return None
        ts, value = entry
        if (time.monotonic() - ts) > self._cache_ttl:
            del self._cache[key]
            return None
        return value

    def _cache_set(self, key: str, value: object) -> None:
        self._cache[key] = (time.monotonic(), value)

    async def search_by_name(self, name: str) -> list[NctProduct]:
        cached = self._cache_get(f"name:{name}")
        if cached is not None:
            return cached  # type: ignore[return-value]
        logger.info("nct stub", method="search_by_name", name=name)
        result: list[NctProduct] = []
        self._cache_set(f"name:{name}", result)
        return result

    async def lookup_by_gtin(self, gtin: str) -> NctProduct | None:
        cached = self._cache_get(f"gtin:{gtin}")
        if cached is not None:
            return cached  # type: ignore[return-value]
        logger.info("nct stub", method="lookup_by_gtin", gtin=gtin)
        return None

    def map_nct_category_to_local(self, nct_category: str) -> int | None:
        logger.info(
            "nct stub", method="map_nct_category_to_local", category=nct_category
        )
        return None
