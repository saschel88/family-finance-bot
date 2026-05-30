from __future__ import annotations

import hashlib

from bot.services.qr import OfdRef
from bot.services.schemas import ReceiptVisionResponse


def _normalize_fiscal(fiscal_id: str | None) -> str | None:
    if not fiscal_id:
        return None
    cleaned = "".join(ch for ch in fiscal_id if ch.isalnum()).lower()
    return cleaned or None


def compute_dedup_key(
    family_id: int,
    vision: ReceiptVisionResponse,
    qr: OfdRef | None = None,
) -> str:
    """Per-family uniqueness key for a receipt.

    Prefers the QR identifiers (strongest, exact), then the OCR fiscal id,
    otherwise a content fingerprint over shop + total + items. The purchase
    date is intentionally excluded so a re-upload of a dateless receipt
    (provisional date = now) still collides.
    """
    fiscal = _normalize_fiscal(vision.fiscal_id)
    if qr is not None:
        base = f"q:{qr.ofd}:{qr.ticket_number}:{qr.registration_number}"
    elif fiscal:
        base = f"f:{fiscal}"
    else:
        shop = (vision.shop_name or "").strip().lower()
        items_sig = "|".join(
            f"{i.name.strip().lower()}={i.total_price}" for i in vision.items
        )
        raw = f"{shop}|{vision.total_amount}|{len(vision.items)}|{items_sig}"
        digest = hashlib.sha256(raw.encode("utf-8")).hexdigest()[:32]
        base = f"h:{digest}"
    return f"{family_id}:{base}"
