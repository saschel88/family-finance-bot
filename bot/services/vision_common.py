from __future__ import annotations

import json
from decimal import Decimal
from typing import Protocol

from pydantic import ValidationError

from bot.core.logging import get_logger
from bot.services.schemas import ReceiptVisionResponse, VisionValidationError

logger = get_logger(__name__)

SYSTEM_PROMPT = """You are a receipt recognition system.
Extract all line items from the receipt and return ONLY valid JSON without markdown.

Response format:
{
  "shop_name": "store name or null",
  "purchased_at": "ISO datetime or null",
  "currency": "KZT",
  "total_amount": 0.00,
  "fiscal_id": "fiscal sign / receipt number or null",
  "items": [
    {
      "name": "item name",
      "quantity": 1.0,
      "unit_price": 0.00,
      "total_price": 0.00,
      "barcode": "barcode string or null"
    }
  ]
}

Rules:
- All amounts as numbers (not strings)
- If currency is not determined — KZT
- If date is unreadable — null
- Item name — as printed on the receipt, no abbreviations
- If a barcode is visible near the item — include it in barcode field
- fiscal_id: the receipt's fiscal sign (ФП/ФПД), fiscal document number, or
  the printed receipt/check number that uniquely identifies this receipt;
  digits only if possible; null if none is visible
- Return ONLY JSON, no explanations"""

USER_TEXT = "Extract all line items from this receipt as JSON."


class VisionEngine(Protocol):
    """Provider-agnostic receipt recognition interface."""

    async def extract(
        self, image_bytes: bytes, mime: str = "image/jpeg"
    ) -> ReceiptVisionResponse: ...


def parse_vision_response(raw_text: str) -> ReceiptVisionResponse:
    """Parse model text into a validated ReceiptVisionResponse.

    Strips optional markdown fences, parses numbers as Decimal, and validates
    with Pydantic. Raises VisionValidationError on malformed JSON or schema.
    """
    text = raw_text.strip()
    if text.startswith("```"):
        text = text.strip("`")
        if text.lstrip().lower().startswith("json"):
            text = text.lstrip()[4:]
        text = text.strip()
    try:
        data = json.loads(text, parse_float=Decimal)
    except json.JSONDecodeError as exc:
        logger.error("vision invalid json", raw=raw_text[:1000])
        raise VisionValidationError("Model returned invalid JSON") from exc
    try:
        return ReceiptVisionResponse.model_validate(data)
    except ValidationError as exc:
        logger.error("vision validation failed", raw=raw_text[:1000])
        raise VisionValidationError(str(exc)) from exc
