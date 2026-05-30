from __future__ import annotations

import httpx
import respx

from bot.services.ofd import OfdClient
from bot.services.qr import OfdRef

_ENDPOINT = "https://cabinet.wofd.kz/api/tickets"


def _ref(ofd: str = "wofd") -> OfdRef:
    return OfdRef(
        host="consumer.wofd.kz",
        ofd=ofd,
        ticket_number="841061549277",
        registration_number="010102737143",
        total="26965.00",
        raw_datetime="20260501T185332",
        url="https://consumer.wofd.kz/?i=841061549277&f=010102737143",
    )


@respx.mock
async def test_fetch_ok_returns_joined_text() -> None:
    respx.get(_ENDPOINT).mock(
        return_value=httpx.Response(
            200,
            json={
                "found": 1,
                "ticket": [
                    {"text": 'ТОО "КАРИ КЗ"', "style": 0},
                    {"text": "GTIN: 04630529181414", "style": 0},
                    {"text": "NTIN: 0200141815130", "style": 0},
                ],
                "ticketUrl": "u",
            },
        )
    )
    text = await OfdClient().fetch_ticket_text(_ref())
    assert text is not None
    assert "GTIN: 04630529181414" in text
    assert "NTIN: 0200141815130" in text


@respx.mock
async def test_fetch_not_found_returns_none() -> None:
    respx.get(_ENDPOINT).mock(
        return_value=httpx.Response(200, json={"found": 0, "ticket": []})
    )
    assert await OfdClient().fetch_ticket_text(_ref()) is None


@respx.mock
async def test_fetch_http_error_returns_none() -> None:
    respx.get(_ENDPOINT).mock(return_value=httpx.Response(500))
    assert await OfdClient().fetch_ticket_text(_ref()) is None


async def test_unsupported_ofd_returns_none() -> None:
    assert await OfdClient().fetch_ticket_text(_ref(ofd="unknown")) is None
