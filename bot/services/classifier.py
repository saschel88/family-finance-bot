from __future__ import annotations

import re
from typing import Protocol

from sqlalchemy.ext.asyncio import AsyncSession

from bot.core.logging import get_logger
from bot.db.models import ProductRule
from bot.db.repository import product as product_repo
from bot.db.repository import rule as rule_repo
from bot.services.identifiers import normalize_gtin, normalize_ntin
from bot.services.nct import NctClient
from bot.services.schemas import ClassifiedItem, ReceiptItemData

logger = get_logger(__name__)

CONFIDENCE_THRESHOLD = 0.7
NCT_NAME_THRESHOLD = 0.85
NCT_NAME_CONFIDENCE = 0.9


class ClassifyFn(Protocol):
    """Injected LLM classification step: item -> (category_id, confidence).

    Implemented per provider (ClaudeClassifier / GeminiClassifier).
    """

    async def __call__(self, item: ReceiptItemData) -> tuple[int | None, float]: ...


class Classifier:
    """Implements the receipt-item classification priority pipeline."""

    def __init__(self, nct: NctClient) -> None:
        self._nct = nct

    async def classify_items(
        self,
        session: AsyncSession,
        items: list[ReceiptItemData],
        claude: ClassifyFn | None = None,
    ) -> list[ClassifiedItem]:
        rules = await rule_repo.find_rules(session)
        return [
            await self._classify_one(session, item, rules, claude) for item in items
        ]

    async def _classify_one(
        self,
        session: AsyncSession,
        item: ReceiptItemData,
        rules: list[ProductRule],
        claude: ClassifyFn | None,
    ) -> ClassifiedItem:
        gtin = normalize_gtin(item.barcode)
        ntin = normalize_ntin(item.ntin)

        # 1. Local catalog by GTIN, then NTIN (no external call).
        if gtin:
            cached = await product_repo.get_by_gtin(session, gtin)
            if cached is not None:
                cached.usage_count += 1
                return ClassifiedItem(
                    item=item,
                    category_id=cached.category_id,
                    confidence=1.0,
                    ntin=cached.ntin or ntin,
                    canonical_name=cached.name,
                    source="catalog_gtin",
                )
        if ntin:
            cached = await product_repo.get_by_ntin(session, ntin)
            if cached is not None:
                cached.usage_count += 1
                return ClassifiedItem(
                    item=item,
                    category_id=cached.category_id,
                    confidence=1.0,
                    ntin=ntin,
                    canonical_name=cached.name,
                    source="catalog_ntin",
                )

        # 2. External NCT by GTIN → cache into local catalog.
        if gtin:
            product = await self._nct.lookup_by_gtin(gtin)
            if product is not None:
                category_id = self._nct.map_nct_category_to_local(product.nct_category)
                if category_id is not None:
                    await product_repo.upsert(
                        session,
                        category_id=category_id,
                        name=product.name,
                        source="nct",
                        gtin=gtin,
                        ntin=product.ntin,
                    )
                    return ClassifiedItem(
                        item=item,
                        category_id=category_id,
                        confidence=1.0,
                        ntin=product.ntin,
                        canonical_name=product.name,
                        source="nct_gtin",
                    )

        # 3. External NCT by name → cache into local catalog.
        products = await self._nct.search_by_name(item.name)
        if products and NCT_NAME_CONFIDENCE > NCT_NAME_THRESHOLD:
            best = products[0]
            category_id = self._nct.map_nct_category_to_local(best.nct_category)
            if category_id is not None:
                await product_repo.upsert(
                    session,
                    category_id=category_id,
                    name=best.name,
                    source="nct",
                    gtin=gtin or best.gtin,
                    ntin=best.ntin,
                )
                return ClassifiedItem(
                    item=item,
                    category_id=category_id,
                    confidence=NCT_NAME_CONFIDENCE,
                    ntin=best.ntin,
                    canonical_name=best.name,
                    source="nct_name",
                )

        # 4. ProductRule matches by name (exact > contains > regex).
        matched = self._match_rules(item.name, rules)
        if matched is not None:
            category_id, confidence, source = matched
            if confidence >= CONFIDENCE_THRESHOLD:
                return ClassifiedItem(
                    item=item,
                    category_id=category_id,
                    confidence=confidence,
                    source=source,
                )

        # 5. LLM classification fallback. Cache confident results that carry
        #    an official identifier (GTIN or NTIN).
        if claude is not None:
            category_id, confidence = await claude(item)
            if category_id is not None and confidence >= CONFIDENCE_THRESHOLD:
                if gtin or ntin:
                    await product_repo.upsert(
                        session,
                        category_id=category_id,
                        name=item.name,
                        source="llm",
                        gtin=gtin,
                        ntin=ntin,
                    )
                return ClassifiedItem(
                    item=item,
                    category_id=category_id,
                    confidence=confidence,
                    ntin=ntin,
                    source="claude",
                )

        # 6. Uncertain — needs user confirmation.
        return ClassifiedItem(item=item, category_id=None, confidence=0.0, ntin=ntin)

    @staticmethod
    def _match_rules(
        name: str, rules: list[ProductRule]
    ) -> tuple[int, float, str] | None:
        lowered = name.lower()

        exact = [r for r in rules if r.match_type == "exact"]
        for r in sorted(exact, key=lambda r: r.confidence, reverse=True):
            if r.pattern.lower() == lowered:
                return r.category_id, r.confidence, "rule_exact"

        contains = [r for r in rules if r.match_type == "contains"]
        for r in sorted(contains, key=lambda r: r.confidence, reverse=True):
            if r.pattern.lower() in lowered:
                return r.category_id, r.confidence, "rule_contains"

        regex = [r for r in rules if r.match_type == "regex"]
        for r in sorted(regex, key=lambda r: r.confidence, reverse=True):
            try:
                if re.search(r.pattern, name, re.IGNORECASE):
                    return r.category_id, r.confidence, "rule_regex"
            except re.error:
                logger.warning("invalid regex rule", pattern=r.pattern)
                continue

        return None
