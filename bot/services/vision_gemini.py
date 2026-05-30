from __future__ import annotations

from google import genai
from google.genai import errors, types

from bot.core.logging import get_logger
from bot.services.gemini_call import generate_with_fallback
from bot.services.schemas import ReceiptVisionResponse, VisionAPIError
from bot.services.vision_common import SYSTEM_PROMPT, USER_TEXT, parse_vision_response

logger = get_logger(__name__)

# Generous to avoid truncation (gemini-2.5 thinking + many-item receipts).
_MAX_TOKENS = 8192


class GeminiVisionService:
    """Google Gemini implementation of VisionEngine (via google-genai SDK).

    Tries the configured model chain (primary → fallback) on each call.
    """

    def __init__(self, client: genai.Client, models: list[str]) -> None:
        self._client = client
        self._models = models

    async def extract(
        self, image_bytes: bytes, mime: str = "image/jpeg"
    ) -> ReceiptVisionResponse:
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
        try:
            response = await generate_with_fallback(
                self._client,
                self._models,
                contents=contents,
                config=config,
                label="vision",
            )
        except errors.APIError as exc:
            logger.error("vision api error", code=exc.code, message=exc.message)
            raise VisionAPIError(str(exc.message)) from exc
        return parse_vision_response(response.text or "")
