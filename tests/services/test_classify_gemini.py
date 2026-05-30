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


async def test_batch_returns_aligned_results() -> None:
    payload = (
        '[{"index": 0, "category_id": 1, "confidence": 0.92},'
        ' {"index": 1, "category_id": 2, "confidence": 0.88}]'
    )
    classifier = GeminiClassifier(make_gemini(payload), ["gemini-test"], _cats())
    results = await classifier([_item("Молоко"), _item("Аспирин")])
    assert results == [(1, 0.92), (2, 0.88)]


async def test_empty_items_no_call() -> None:
    client = make_gemini("[]")
    classifier = GeminiClassifier(client, ["gemini-test"], _cats())
    assert await classifier([]) == []
    client.aio.models.generate_content.assert_not_called()


async def test_missing_index_defaults_to_uncertain() -> None:
    # Model returns only one of two items.
    payload = '[{"index": 0, "category_id": 1, "confidence": 0.9}]'
    classifier = GeminiClassifier(make_gemini(payload), ["gemini-test"], _cats())
    results = await classifier([_item("Молоко"), _item("Загадка")])
    assert results == [(1, 0.9), (None, 0.0)]


async def test_api_error_degrades_gracefully() -> None:
    client = make_gemini("[]")
    response = requests.Response()
    response.status_code = 500
    response._content = b'{"error": {"message": "x", "status": "INTERNAL"}}'
    client.aio.models.generate_content = AsyncMock(
        side_effect=errors.ServerError(500, response)
    )
    classifier = GeminiClassifier(client, ["gemini-test"], _cats())
    assert await classifier([_item("A"), _item("B")]) == [(None, 0.0), (None, 0.0)]


async def test_malformed_json_degrades_gracefully() -> None:
    classifier = GeminiClassifier(make_gemini("not json"), ["gemini-test"], _cats())
    assert await classifier([_item("A")]) == [(None, 0.0)]
