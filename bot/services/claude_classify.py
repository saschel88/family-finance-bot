from __future__ import annotations

import json

import anthropic

from bot.core.logging import get_logger
from bot.db.models import Category
from bot.services.classify_common import (
    CLASSIFY_MAX_TOKENS,
    CLASSIFY_SYSTEM,
    build_batch_prompt,
    build_catalog,
    parse_batch_classify,
)
from bot.services.schemas import ReceiptItemData

logger = get_logger(__name__)


class ClaudeClassifier:
    """Batch Claude classification step.

    Callable: given a list of items, returns a list of (category_id,
    confidence) aligned by index — one LLM request for the whole batch.
    """

    def __init__(
        self,
        client: anthropic.AsyncAnthropic,
        model: str,
        categories: list[Category],
    ) -> None:
        self._client = client
        self._model = model
        self._catalog = build_catalog(categories)

    async def __call__(
        self, items: list[ReceiptItemData]
    ) -> list[tuple[int | None, float]]:
        if not items:
            return []
        prompt = build_batch_prompt(self._catalog, items)
        try:
            response = await self._client.messages.create(
                model=self._model,
                max_tokens=CLASSIFY_MAX_TOKENS,
                system=CLASSIFY_SYSTEM,
                messages=[{"role": "user", "content": prompt}],
            )
            return parse_batch_classify(self._first_text(response), len(items))
        except (anthropic.APIError, json.JSONDecodeError, ValueError) as exc:
            logger.warning("claude classify failed", error=str(exc))
            return [(None, 0.0)] * len(items)

    @staticmethod
    def _first_text(response: anthropic.types.Message) -> str:
        for block in response.content:
            if getattr(block, "type", None) == "text":
                return getattr(block, "text", "")
        return ""
