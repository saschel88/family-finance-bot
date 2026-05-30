from __future__ import annotations


def normalize_gtin(barcode: str | None) -> str | None:
    """Normalize a printed barcode to a digits-only GTIN, or None."""
    if not barcode:
        return None
    digits = "".join(ch for ch in barcode if ch.isdigit())
    return digits or None


def normalize_ntin(ntin: str | None) -> str | None:
    """Normalize an NTIN/KZTIN to digits only, or None."""
    if not ntin:
        return None
    digits = "".join(ch for ch in ntin if ch.isdigit())
    return digits or None
