from __future__ import annotations

import json

from bot.db.models import Category
from bot.services.schemas import ReceiptItemData

CLASSIFY_SYSTEM = (
    "Ты классификатор товаров из чека. Тебе дают список категорий и "
    "пронумерованный список товаров. Верни ТОЛЬКО JSON-массив — по одному "
    "объекту на каждый товар, в формате "
    '[{"index": <int>, "category_id": <int|null>, "confidence": <0.0-1.0>}]. '
    "index — номер товара из запроса. Если не уверен в категории — confidence "
    "ниже 0.7. Без пояснений, только JSON-массив."
)

# Generous budget — gemini-2.5 spends tokens on "thinking", and a batch covers
# every unresolved item at once, so the JSON array can be sizable.
CLASSIFY_MAX_TOKENS = 4096


def build_catalog(categories: list[Category]) -> str:
    return "\n".join(f"{c.id}: {c.name}" for c in categories)


def build_batch_prompt(catalog: str, items: list[ReceiptItemData]) -> str:
    products = "\n".join(f"{i}: {item.name}" for i, item in enumerate(items))
    return f"Категории:\n{catalog}\n\nТовары:\n{products}\n\nОтвет JSON-массив:"


def _strip_fences(text: str) -> str:
    text = text.strip()
    if text.startswith("```"):
        text = text.strip("`")
        if text.lstrip().lower().startswith("json"):
            text = text.lstrip()[4:]
        text = text.strip()
    return text


def parse_batch_classify(text: str, count: int) -> list[tuple[int | None, float]]:
    """Parse the classifier JSON array into per-item (category_id, confidence).

    Returns a list of length `count` aligned by the `index` field; items the
    model omitted default to (None, 0.0). Raises json.JSONDecodeError /
    ValueError on malformed input — callers catch and degrade.
    """
    data = json.loads(_strip_fences(text))
    if not isinstance(data, list):
        raise ValueError("expected a JSON array")
    results: list[tuple[int | None, float]] = [(None, 0.0)] * count
    for obj in data:
        idx = int(obj["index"])
        if not 0 <= idx < count:
            continue
        category_id = obj.get("category_id")
        confidence = float(obj.get("confidence", 0.0))
        results[idx] = (
            int(category_id) if category_id is not None else None,
            confidence,
        )
    return results
