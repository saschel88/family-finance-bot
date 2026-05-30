from __future__ import annotations

import asyncio

from google import genai
from google.genai import errors, types

from bot.core.logging import get_logger
from bot.services.schemas import ReceiptVisionResponse, VisionAPIError
from bot.services.vision_common import SYSTEM_PROMPT, USER_TEXT, parse_vision_response

logger = get_logger(__name__)

_MAX_RETRIES = 3
_BACKOFF_SECONDS = (2, 4, 8)
# Generous to avoid truncation (gemini-2.5 thinking + many-item receipts).
_MAX_TOKENS = 8192
_RETRYABLE_CODES = {429, 500, 502, 503, 504}


class GeminiVisionService:
    """Google Gemini implementation of VisionEngine (via google-genai SDK)."""

    def __init__(self, client: genai.Client, model: str) -> None:
        self._client = client
        self._model = model

    async def extract(
        self, image_bytes: bytes, mime: str = "image/jpeg"
    ) -> ReceiptVisionResponse:
        raw_text = await self._call_with_retries(image_bytes, mime)
        return parse_vision_response(raw_text)

    async def _call_with_retries(self, image_bytes: bytes, mime: str) -> str:
        config = types.GenerateContentConfig(
            system_instruction=SYSTEM_PROMPT,
            response_mime_type="application/json",
            max_output_tokens=_MAX_TOKENS,
            temperature=0.0,
        )
        contents = [
            types.Part.from_bytes(data=image_bytes, mime_type=mime),
            USER_TEXT,
        ]
        last_error: Exception | None = None
        for attempt in range(_MAX_RETRIES):
            try:
                response = await self._client.aio.models.generate_content(
                    model=self._model,
                    contents=contents,
                    config=config,
                )
                return response.text or ""
            except errors.APIError as exc:
                if exc.code in _RETRYABLE_CODES:
                    last_error = exc
                    logger.warning("vision retry", attempt=attempt + 1, code=exc.code)
                    if attempt < _MAX_RETRIES - 1:
                        await asyncio.sleep(_BACKOFF_SECONDS[attempt])
                    continue
                logger.error("vision api error", code=exc.code, message=exc.message)
                raise VisionAPIError(str(exc.message)) from exc
        logger.error("vision exhausted retries")
        raise VisionAPIError("Gemini Vision failed after retries") from last_error
