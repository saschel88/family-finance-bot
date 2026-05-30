from __future__ import annotations

import json

from google import genai
from google.genai import errors, types

from bot.core.logging import get_logger
from bot.db.models import Category
from bot.services.classify_common import (
    CLASSIFY_MAX_TOKENS,
    CLASSIFY_SYSTEM,
    build_batch_prompt,
    build_catalog,
    parse_batch_classify,
)
from bot.services.gemini_call import generate_with_fallback
from bot.services.schemas import ReceiptItemData

logger = get_logger(__name__)


class GeminiClassifier:
    """Batch Gemini classification step over the configured model chain.

    Callable: given a list of items, returns a list of (category_id,
    confidence) aligned by index — one LLM request for the whole batch.
    """

    def __init__(
        self,
        client: genai.Client,
        models: list[str],
        categories: list[Category],
    ) -> None:
        self._client = client
        self._models = models
        self._catalog = build_catalog(categories)

    async def __call__(
        self, items: list[ReceiptItemData]
    ) -> list[tuple[int | None, float]]:
        if not items:
            return []
        prompt = build_batch_prompt(self._catalog, items)
        config = types.GenerateContentConfig(
            system_instruction=CLASSIFY_SYSTEM,
            response_mime_type="application/json",
            max_output_tokens=CLASSIFY_MAX_TOKENS,
            temperature=0.0,
        )
        try:
            response = await generate_with_fallback(
                self._client,
                self._models,
                contents=[prompt],
                config=config,
                label="classify",
            )
            return parse_batch_classify(response.text or "", len(items))
        except (errors.APIError, json.JSONDecodeError, ValueError) as exc:
            logger.warning("gemini classify failed", error=str(exc))
            return [(None, 0.0)] * len(items)
