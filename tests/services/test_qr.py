from __future__ import annotations

from bot.services.qr import decode_qr, parse_ofd_url

_URL = (
    "https://consumer.wofd.kz/?i=841061549277&f=010102737143"
    "&s=26965.00&t=20260501T185332"
)


def test_parse_wofd_url() -> None:
    ref = parse_ofd_url(_URL)
    assert ref is not None
    assert ref.ofd == "wofd"
    assert ref.ticket_number == "841061549277"
    assert ref.registration_number == "010102737143"
    assert ref.total == "26965.00"
    assert ref.raw_datetime == "20260501T185332"


def test_non_ofd_url_returns_none() -> None:
    assert parse_ofd_url("https://example.com/?i=1&f=2") is None


def test_missing_params_returns_none() -> None:
    assert parse_ofd_url("https://consumer.wofd.kz/?s=1") is None


def test_empty_returns_none() -> None:
    assert parse_ofd_url("") is None


def test_decode_qr_on_garbage_returns_none() -> None:
    assert decode_qr(b"not an image") is None
