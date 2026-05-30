from __future__ import annotations

import json

from bot.db.models import Category

CLASSIFY_SYSTEM = (
    "Ты классификатор товаров из чека. Тебе дают название товара и список "
    "категорий. Верни ТОЛЬКО JSON вида "
    '{"category_id": <int|null>, "confidence": <0.0-1.0>} без пояснений. '
    "Если не уверен — confidence ниже 0.7."
)

# gemini-2.5 models spend output tokens on internal "thinking"; a tight budget
# (e.g. 256) can be fully consumed before any JSON is emitted, yielding empty
# text. Keep this generous — the actual answer is tiny.
CLASSIFY_MAX_TOKENS = 2048


def build_catalog(categories: list[Category]) -> str:
    return "\n".join(f"{c.id}: {c.name}" for c in categories)


def build_prompt(catalog: str, name: str) -> str:
    return f"Категории:\n{catalog}\n\nТовар: {name}\nОтвет JSON:"


def parse_classify(text: str) -> tuple[int | None, float]:
    """Parse the classifier JSON into (category_id, confidence).

    Raises json.JSONDecodeError / ValueError on malformed input — callers
    catch and degrade to (None, 0.0).
    """
    text = text.strip()
    if text.startswith("```"):
        text = text.strip("`")
        if text.lstrip().lower().startswith("json"):
            text = text.lstrip()[4:]
        text = text.strip()
    data = json.loads(text)
    category_id = data.get("category_id")
    confidence = float(data.get("confidence", 0.0))
    return (int(category_id) if category_id is not None else None, confidence)
