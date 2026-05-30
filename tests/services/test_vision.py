from __future__ import annotations

from decimal import Decimal
from unittest.mock import AsyncMock, MagicMock

import anthropic
import httpx
import pytest

from bot.services.schemas import VisionAPIError, VisionValidationError
from bot.services.vision import VisionService

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


def _request() -> httpx.Request:
    return httpx.Request("POST", "https://api.anthropic.com/v1/messages")


def _response(status: int) -> httpx.Response:
    return httpx.Response(status, request=_request())


def _client_returning(text: str) -> AsyncMock:
    client = AsyncMock()
    block = MagicMock()
    block.type = "text"
    block.text = text
    response = MagicMock()
    response.content = [block]
    client.messages.create = AsyncMock(return_value=response)
    return client


async def test_happy_path() -> None:
    client = _client_returning(_VALID_JSON)
    service = VisionService(client, "claude-test")
    result = await service.extract(b"image-bytes")
    assert result.shop_name == "Магнум"
    assert result.total_amount == Decimal("1500.50")
    assert len(result.items) == 1
    assert result.items[0].name == "Хлеб"


async def test_markdown_fenced_json_is_stripped() -> None:
    fenced = f"```json\n{_VALID_JSON}\n```"
    service = VisionService(_client_returning(fenced), "claude-test")
    result = await service.extract(b"image-bytes")
    assert result.total_amount == Decimal("1500.50")


async def test_garbage_raises_validation_error() -> None:
    service = VisionService(_client_returning("not json at all"), "claude-test")
    with pytest.raises(VisionValidationError):
        await service.extract(b"image-bytes")


async def test_missing_total_amount_raises_validation_error() -> None:
    service = VisionService(
        _client_returning('{"items": [], "currency": "KZT"}'), "claude-test"
    )
    with pytest.raises(VisionValidationError):
        await service.extract(b"image-bytes")


async def test_retry_on_timeout_then_success(mocker: object) -> None:
    sleep = AsyncMock()
    import bot.services.vision as vision_module

    mocker.patch.object(vision_module.asyncio, "sleep", sleep)  # type: ignore[attr-defined]

    client = _client_returning(_VALID_JSON)
    block = MagicMock(type="text", text=_VALID_JSON)
    ok_response = MagicMock(content=[block])
    client.messages.create = AsyncMock(
        side_effect=[
            anthropic.APITimeoutError(request=_request()),
            anthropic.APITimeoutError(request=_request()),
            ok_response,
        ]
    )
    service = VisionService(client, "claude-test")
    result = await service.extract(b"image-bytes")

    assert result.total_amount == Decimal("1500.50")
    assert client.messages.create.await_count == 3
    assert [c.args[0] for c in sleep.await_args_list] == [2, 4]


async def test_status_error_raises_vision_api_error() -> None:
    client = _client_returning(_VALID_JSON)
    client.messages.create = AsyncMock(
        side_effect=anthropic.APIStatusError("boom", response=_response(500), body=None)
    )
    service = VisionService(client, "claude-test")
    with pytest.raises(VisionAPIError):
        await service.extract(b"image-bytes")


async def test_exhausted_retries_raises_vision_api_error(mocker: object) -> None:
    import bot.services.vision as vision_module

    mocker.patch.object(vision_module.asyncio, "sleep", AsyncMock())  # type: ignore[attr-defined]
    client = _client_returning(_VALID_JSON)
    client.messages.create = AsyncMock(
        side_effect=anthropic.APITimeoutError(request=_request())
    )
    service = VisionService(client, "claude-test")
    with pytest.raises(VisionAPIError):
        await service.extract(b"image-bytes")
    assert client.messages.create.await_count == 3
