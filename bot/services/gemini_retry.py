from __future__ import annotations

import re

from google.genai import errors

# Transient Gemini error codes worth retrying (incl. 429 rate-limit).
RETRYABLE_CODES = {429, 500, 502, 503, 504}
MAX_RETRIES = 3
# Default exponential backoff when the server gives no hint.
_DEFAULT_BACKOFF = (2.0, 4.0, 8.0)
# Cap a single wait so a handler never blocks too long.
_MAX_DELAY = 45.0

_RETRY_RE = re.compile(r"retry in ([\d.]+)s", re.IGNORECASE)


def parse_retry_delay(message: str | None) -> float | None:
    """Extract the server-suggested retry delay (seconds) from a 429 message."""
    if not message:
        return None
    match = _RETRY_RE.search(message)
    return float(match.group(1)) if match else None


def next_delay(exc: errors.APIError, attempt: int) -> float:
    """Seconds to wait before the next attempt: honor the server hint when
    present (capped), else exponential backoff."""
    suggested = parse_retry_delay(getattr(exc, "message", None)) or parse_retry_delay(
        str(exc)
    )
    if suggested is not None:
        return min(suggested + 1.0, _MAX_DELAY)
    idx = min(attempt, len(_DEFAULT_BACKOFF) - 1)
    return _DEFAULT_BACKOFF[idx]
