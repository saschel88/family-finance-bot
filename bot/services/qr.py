from __future__ import annotations

import io
from dataclasses import dataclass
from urllib.parse import parse_qs, urlparse

import zxingcpp
from PIL import Image

from bot.core.logging import get_logger

logger = get_logger(__name__)


@dataclass
class OfdRef:
    """Parameters decoded from a Kazakhstan OFD receipt QR link."""

    host: str  # e.g. "consumer.wofd.kz"
    ofd: str  # normalized operator key, e.g. "wofd"
    ticket_number: str  # QR param i (fiscal sign)
    registration_number: str  # QR param f (KKM registration number)
    total: str | None  # QR param s
    raw_datetime: str | None  # QR param t, e.g. "20260501T185332"
    url: str


_OFD_KEYS = ("wofd", "oofd", "kofd", "ofd1")


def decode_qr(image_bytes: bytes) -> str | None:
    """Decode the first QR/barcode payload from an image, or None."""
    try:
        image = Image.open(io.BytesIO(image_bytes))
        results = zxingcpp.read_barcodes(image)
    except Exception as exc:  # noqa: BLE001 - decoding is best-effort
        logger.warning("qr decode failed", error=str(exc))
        return None
    for result in results:
        if result.text:
            return str(result.text)
    return None


def parse_ofd_url(url: str) -> OfdRef | None:
    """Parse an OFD consumer URL into an OfdRef, or None if it is not one."""
    if not url or "ofd" not in url.lower():
        return None
    parsed = urlparse(url)
    query = parse_qs(parsed.query)
    ticket = query.get("i", [None])[0]
    registration = query.get("f", [None])[0]
    if not ticket or not registration:
        return None
    host = parsed.netloc.lower()
    ofd = next((key for key in _OFD_KEYS if key in host), "")
    return OfdRef(
        host=host,
        ofd=ofd,
        ticket_number=ticket,
        registration_number=registration,
        total=query.get("s", [None])[0],
        raw_datetime=query.get("t", [None])[0],
        url=url,
    )
