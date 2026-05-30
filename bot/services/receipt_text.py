from __future__ import annotations

from typing import Protocol

import anthropic
from google import genai
from google.genai import errors, types

from bot.core.logging import get_logger
from bot.services.schemas import ReceiptVisionResponse, VisionAPIError
from bot.services.vision_common import parse_vision_response

logger = get_logger(__name__)

# Generous budget: gemini-2.5 spends tokens on "thinking", and a full receipt
# with many long item names produces a sizable JSON — too small a budget
# truncates the output (finish_reason=MAX_TOKENS) and breaks JSON parsing.
_MAX_TOKENS = 8192

TEXT_SYSTEM_PROMPT = """You parse the exact text of a Kazakhstan fiscal receipt
(already digitized — NOT an image). Return ONLY valid JSON, no markdown.

Format:
{
  "shop_name": "seller name or null",
  "purchased_at": "ISO datetime or null",
  "currency": "KZT",
  "total_amount": 0.00,
  "fiscal_id": "fiscal sign (Фискальдық белгі / Фискальный признак) or null",
  "items": [
    {
      "name": "item name",
      "quantity": 1.0,
      "unit_price": 0.00,
      "total_price": 0.00,
      "barcode": "GTIN digits or null",
      "ntin": "NTIN digits or null"
    }
  ]
}

Rules:
- Do NOT invent data — use only what is in the text.
- Numbers: spaces / non-breaking spaces are thousands separators and comma is
  the decimal point — "12 243,00" → 12243.00. Output numbers, not strings.
- A line like "1 (Дана/Штука) x 12 243,00₸ = 12 243,00₸" gives quantity,
  unit_price and total_price for the item directly above it.
- An item name may span several lines — join them into one name.
- barcode: take from the "GTIN:" line for that item (digits only), else null.
- ntin: take from the "NTIN:" line for that item (digits only), else null.
- total_amount: the БАРЛЫҒЫ / ИТОГО total.
- Return ONLY JSON."""


class ReceiptTextParser(Protocol):
    """Parses OFD receipt text into a structured ReceiptVisionResponse."""

    async def parse(self, text: str) -> ReceiptVisionResponse: ...


class GeminiReceiptParser:
    def __init__(self, client: genai.Client, model: str) -> None:
        self._client = client
        self._model = model

    async def parse(self, text: str) -> ReceiptVisionResponse:
        config = types.GenerateContentConfig(
            system_instruction=TEXT_SYSTEM_PROMPT,
            response_mime_type="application/json",
            max_output_tokens=_MAX_TOKENS,
            temperature=0.0,
        )
        try:
            response = await self._client.aio.models.generate_content(
                model=self._model, contents=[text], config=config
            )
        except errors.APIError as exc:
            logger.error("ofd parse api error", code=exc.code)
            raise VisionAPIError(str(exc.message)) from exc
        return parse_vision_response(response.text or "")


class ClaudeReceiptParser:
    def __init__(self, client: anthropic.AsyncAnthropic, model: str) -> None:
        self._client = client
        self._model = model

    async def parse(self, text: str) -> ReceiptVisionResponse:
        try:
            response = await self._client.messages.create(
                model=self._model,
                max_tokens=_MAX_TOKENS,
                system=TEXT_SYSTEM_PROMPT,
                messages=[{"role": "user", "content": text}],
            )
        except anthropic.APIStatusError as exc:
            logger.error("ofd parse api error", status_code=exc.status_code)
            raise VisionAPIError(str(exc.message)) from exc
        raw = ""
        for block in response.content:
            if getattr(block, "type", None) == "text":
                raw = getattr(block, "text", "")
                break
        return parse_vision_response(raw)
