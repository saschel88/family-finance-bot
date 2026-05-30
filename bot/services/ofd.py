from __future__ import annotations

import httpx

from bot.core.logging import get_logger
from bot.services.qr import OfdRef

logger = get_logger(__name__)

_HTTP_TIMEOUT = httpx.Timeout(10.0)

# Per-operator consumer API endpoints. Only WOFD is verified so far; others are
# added once we have a confirmed request capture for them.
_ENDPOINTS: dict[str, str] = {
    "wofd": "https://cabinet.wofd.kz/api/tickets",
}


def _ticket_date(raw_datetime: str | None) -> str | None:
    """Convert QR `t` (e.g. '20260501T185332') to 'YYYY-MM-DD'."""
    if not raw_datetime or len(raw_datetime) < 8:
        return None
    d = raw_datetime[:8]
    if not d.isdigit():
        return None
    return f"{d[0:4]}-{d[4:6]}-{d[6:8]}"


class OfdClient:
    """Fetches the authoritative receipt text from an OFD consumer API."""

    def __init__(self, http: httpx.AsyncClient | None = None) -> None:
        self._http = http

    async def fetch_ticket_text(self, ref: OfdRef) -> str | None:
        """Return the receipt as joined text lines, or None if unavailable.

        Any failure (unsupported OFD, network/TLS error, not found) returns
        None so the caller can fall back to vision OCR.
        """
        endpoint = _ENDPOINTS.get(ref.ofd)
        ticket_date = _ticket_date(ref.raw_datetime)
        if endpoint is None or ticket_date is None:
            logger.info("ofd unsupported", ofd=ref.ofd, host=ref.host)
            return None
        params = {
            "registrationNumber": ref.registration_number,
            "ticketNumber": ref.ticket_number,
            "ticketDate": ticket_date,
        }
        try:
            if self._http is not None:
                response = await self._http.get(
                    endpoint, params=params, timeout=_HTTP_TIMEOUT
                )
            else:
                async with httpx.AsyncClient(timeout=_HTTP_TIMEOUT) as client:
                    response = await client.get(endpoint, params=params)
            response.raise_for_status()
            data = response.json()
        except (httpx.HTTPError, ValueError) as exc:
            logger.warning("ofd fetch failed", ofd=ref.ofd, error=str(exc))
            return None

        if not data.get("found"):
            logger.info("ofd not found", ticket=ref.ticket_number)
            return None
        lines = data.get("ticket") or []
        text = "\n".join(str(line.get("text", "")).rstrip() for line in lines)
        return text or None
