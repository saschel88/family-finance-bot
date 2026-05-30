from __future__ import annotations

from datetime import datetime
from decimal import Decimal

from pydantic import BaseModel, Field


class ReceiptItemData(BaseModel):
    """A single line item extracted from a receipt (vision or OFD)."""

    name: str
    quantity: Decimal = Decimal(1)
    unit_price: Decimal = Decimal(0)
    total_price: Decimal = Decimal(0)
    barcode: str | None = None  # GTIN, when printed
    ntin: str | None = None  # NTIN/KZTIN, when provided (e.g. by OFD)


class ReceiptVisionResponse(BaseModel):
    """Validated Claude Vision response for a receipt."""

    shop_name: str | None = None
    purchased_at: datetime | None = None
    currency: str = "KZT"
    total_amount: Decimal
    fiscal_id: str | None = None
    items: list[ReceiptItemData] = Field(default_factory=list)


class NctProduct(BaseModel):
    """A product record from the National Catalog."""

    gtin: str | None = None
    ntin: str | None = None
    name: str
    nct_category: str


class ClassifiedItem(BaseModel):
    """An item paired with the result of the classification pipeline.

    gtin is sourced from the receipt barcode (item.barcode); ntin (NTIN/KZTIN)
    comes from National Catalog enrichment when available.
    """

    item: ReceiptItemData
    category_id: int | None = None
    confidence: float = 0.0
    ntin: str | None = None
    canonical_name: str | None = None
    source: str = "unknown"
    # catalog_gtin | catalog_ntin | nct_gtin | nct_name | rule_exact
    # | rule_contains | rule_regex | claude | unknown


class VisionError(Exception):
    """Base error for the vision service."""


class VisionValidationError(VisionError):
    """Claude returned a response that failed JSON/Pydantic validation."""


class VisionAPIError(VisionError):
    """Claude API call failed after retries."""
