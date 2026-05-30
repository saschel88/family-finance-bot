from __future__ import annotations

import requests
from google.genai import errors

from bot.services.gemini_retry import next_delay, parse_retry_delay


def _err(message: str, code: int = 429) -> errors.APIError:
    response = requests.Response()
    response.status_code = code
    response._content = b"{}"
    exc = errors.APIError(code, response)
    exc.message = message
    return exc


def test_parse_retry_delay_found() -> None:
    assert parse_retry_delay("Quota exceeded. Please retry in 43.6s.") == 43.6


def test_parse_retry_delay_absent() -> None:
    assert parse_retry_delay("some other error") is None
    assert parse_retry_delay(None) is None


def test_next_delay_honors_server_hint_capped() -> None:
    # 43.6 + 1 buffer = 44.6, under the 45s cap.
    assert next_delay(_err("Please retry in 43.6s"), 0) == 44.6
    # Huge hint is capped at 45s.
    assert next_delay(_err("Please retry in 600s"), 0) == 45.0


def test_next_delay_falls_back_to_backoff() -> None:
    assert next_delay(_err("no hint", code=503), 0) == 2.0
    assert next_delay(_err("no hint", code=503), 1) == 4.0
    assert next_delay(_err("no hint", code=503), 2) == 8.0
