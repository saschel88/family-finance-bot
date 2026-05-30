from __future__ import annotations

from decimal import Decimal
from unittest.mock import AsyncMock, MagicMock

import pytest
import requests
from google.genai import errors

from bot.services.schemas import VisionAPIError, VisionValidationError
from bot.services.vision_gemini import GeminiVisionService
from tests.conftest import make_gemini

_VALID_JSON = """
{
  "shop_name": "Магнум",
  "purchased_at": "2026-05-01T12:00:00",
  "currency": "KZT",
  "total_amount": 1500.50,
  "items": [
    {"name": "Хлеб", "quantity": 1, "unit_price": 250.00,
     "total_price": 250.00, "barcode": null}
  ]
}
"""


def _api_error(code: int) -> errors.APIError:
    response = requests.Response()
    response.status_code = code
    response._content = b'{"error": {"message": "boom", "status": "UNAVAILABLE"}}'
    if code >= 500:
        return errors.ServerError(code, response)
    return errors.ClientError(code, response)


async def test_happy_path() -> None:
    service = GeminiVisionService(make_gemini(_VALID_JSON), "gemini-test")
    result = await service.extract(b"image-bytes")
    assert result.shop_name == "Магнум"
    assert result.total_amount == Decimal("1500.50")
    assert result.items[0].name == "Хлеб"


async def test_markdown_fenced_json_is_stripped() -> None:
    fenced = f"```json\n{_VALID_JSON}\n```"
    service = GeminiVisionService(make_gemini(fenced), "gemini-test")
    result = await service.extract(b"image-bytes")
    assert result.total_amount == Decimal("1500.50")


async def test_garbage_raises_validation_error() -> None:
    service = GeminiVisionService(make_gemini("not json"), "gemini-test")
    with pytest.raises(VisionValidationError):
        await service.extract(b"image-bytes")


async def test_retry_on_503_then_success(mocker: object) -> None:
    import bot.services.vision_gemini as module

    mocker.patch.object(module.asyncio, "sleep", AsyncMock())  # type: ignore[attr-defined]
    client = make_gemini(_VALID_JSON)
    ok = MagicMock()
    ok.text = _VALID_JSON
    client.aio.models.generate_content = AsyncMock(
        side_effect=[_api_error(503), _api_error(503), ok]
    )
    service = GeminiVisionService(client, "gemini-test")
    result = await service.extract(b"image-bytes")
    assert result.total_amount == Decimal("1500.50")
    assert client.aio.models.generate_content.await_count == 3


async def test_non_retryable_error_raises_api_error() -> None:
    client = make_gemini(_VALID_JSON)
    client.aio.models.generate_content = AsyncMock(side_effect=_api_error(400))
    service = GeminiVisionService(client, "gemini-test")
    with pytest.raises(VisionAPIError):
        await service.extract(b"image-bytes")
    assert client.aio.models.generate_content.await_count == 1


async def test_exhausted_retries_raises_api_error(mocker: object) -> None:
    import bot.services.vision_gemini as module

    mocker.patch.object(module.asyncio, "sleep", AsyncMock())  # type: ignore[attr-defined]
    client = make_gemini(_VALID_JSON)
    client.aio.models.generate_content = AsyncMock(side_effect=_api_error(503))
    service = GeminiVisionService(client, "gemini-test")
    with pytest.raises(VisionAPIError):
        await service.extract(b"image-bytes")
    assert client.aio.models.generate_content.await_count == 3
