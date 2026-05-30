from __future__ import annotations

import json

from google import genai
from google.genai import errors, types

from bot.core.logging import get_logger
from bot.db.models import Category
from bot.services.classify_common import (
    CLASSIFY_MAX_TOKENS,
    CLASSIFY_SYSTEM,
    build_catalog,
    build_prompt,
    parse_classify,
)
from bot.services.schemas import ReceiptItemData

logger = get_logger(__name__)


class GeminiClassifier:
    """Minimal single-item Gemini classification step.

    Instances are callable and satisfy the classifier's ClassifyFn
    protocol: given an item, return (category_id, confidence).
    """

    def __init__(
        self,
        client: genai.Client,
        model: str,
        categories: list[Category],
    ) -> None:
        self._client = client
        self._model = model
        self._catalog = build_catalog(categories)

    async def __call__(self, item: ReceiptItemData) -> tuple[int | None, float]:
        prompt = build_prompt(self._catalog, item.name)
        config = types.GenerateContentConfig(
            system_instruction=CLASSIFY_SYSTEM,
            response_mime_type="application/json",
            max_output_tokens=CLASSIFY_MAX_TOKENS,
            temperature=0.0,
        )
        try:
            response = await self._client.aio.models.generate_content(
                model=self._model,
                contents=[prompt],
                config=config,
            )
            return parse_classify(response.text or "")
        except (errors.APIError, json.JSONDecodeError, ValueError) as exc:
            logger.warning("gemini classify failed", error=str(exc))
            return None, 0.0
