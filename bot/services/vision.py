from __future__ import annotations

import asyncio
import base64

import anthropic
from anthropic.types import ImageBlockParam, MessageParam, TextBlockParam

from bot.core.logging import get_logger
from bot.services.schemas import ReceiptVisionResponse, VisionAPIError
from bot.services.vision_common import SYSTEM_PROMPT, USER_TEXT, parse_vision_response

logger = get_logger(__name__)

_MAX_RETRIES = 3
_BACKOFF_SECONDS = (2, 4, 8)
_MAX_TOKENS = 4096


class VisionService:
    """Claude Vision implementation of VisionEngine."""

    def __init__(self, client: anthropic.AsyncAnthropic, model: str) -> None:
        self._client = client
        self._model = model

    async def extract(
        self, image_bytes: bytes, mime: str = "image/jpeg"
    ) -> ReceiptVisionResponse:
        raw_text = await self._call_with_retries(image_bytes, mime)
        return parse_vision_response(raw_text)

    async def _call_with_retries(self, image_bytes: bytes, mime: str) -> str:
        b64 = base64.standard_b64encode(image_bytes).decode("ascii")
        image_block: ImageBlockParam = {
            "type": "image",
            "source": {
                "type": "base64",
                "media_type": mime,  # type: ignore[typeddict-item]
                "data": b64,
            },
        }
        text_block: TextBlockParam = {"type": "text", "text": USER_TEXT}
        messages: list[MessageParam] = [
            {"role": "user", "content": [image_block, text_block]}
        ]
        last_error: Exception | None = None
        for attempt in range(_MAX_RETRIES):
            try:
                response = await self._client.messages.create(
                    model=self._model,
                    max_tokens=_MAX_TOKENS,
                    system=SYSTEM_PROMPT,
                    messages=messages,
                )
                return self._extract_text(response)
            except (
                anthropic.RateLimitError,
                anthropic.APITimeoutError,
            ) as exc:
                last_error = exc
                logger.warning(
                    "vision retry",
                    attempt=attempt + 1,
                    error=type(exc).__name__,
                )
                if attempt < _MAX_RETRIES - 1:
                    await asyncio.sleep(_BACKOFF_SECONDS[attempt])
            except anthropic.APIStatusError as exc:
                logger.error(
                    "vision api status error",
                    status_code=exc.status_code,
                    message=str(exc.message),
                )
                raise VisionAPIError(str(exc.message)) from exc
        logger.error("vision exhausted retries")
        raise VisionAPIError("Claude Vision failed after retries") from last_error

    @staticmethod
    def _extract_text(response: anthropic.types.Message) -> str:
        for block in response.content:
            if getattr(block, "type", None) == "text":
                return getattr(block, "text", "")
        return ""
