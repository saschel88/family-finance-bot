from __future__ import annotations

from unittest.mock import AsyncMock

import requests
from google.genai import errors

from bot.db.models import Category
from bot.services.classify_gemini import GeminiClassifier
from bot.services.schemas import ReceiptItemData
from tests.conftest import make_gemini


def _item(name: str) -> ReceiptItemData:
    return ReceiptItemData(
        name=name,
        quantity=1,  # type: ignore[arg-type]
        unit_price=10,  # type: ignore[arg-type]
        total_price=10,  # type: ignore[arg-type]
    )


def _cats() -> list[Category]:
    return [
        Category(id=1, name="Продукты", emoji="🛒"),
        Category(id=2, name="Аптека", emoji="💊"),
    ]


async def test_returns_category_and_confidence() -> None:
    client = make_gemini('{"category_id": 2, "confidence": 0.91}')
    classifier = GeminiClassifier(client, "gemini-test", _cats())
    category_id, confidence = await classifier(_item("Аспирин"))
    assert category_id == 2
    assert confidence == 0.91


async def test_api_error_degrades_gracefully() -> None:
    client = make_gemini("{}")
    response = requests.Response()
    response.status_code = 500
    response._content = b'{"error": {"message": "x", "status": "INTERNAL"}}'
    client.aio.models.generate_content = AsyncMock(
        side_effect=errors.ServerError(500, response)
    )
    classifier = GeminiClassifier(client, "gemini-test", _cats())
    category_id, confidence = await classifier(_item("Нечто"))
    assert category_id is None
    assert confidence == 0.0


async def test_malformed_json_degrades_gracefully() -> None:
    client = make_gemini("not json")
    classifier = GeminiClassifier(client, "gemini-test", _cats())
    category_id, confidence = await classifier(_item("Нечто"))
    assert category_id is None
    assert confidence == 0.0
