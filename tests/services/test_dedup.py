from __future__ import annotations

from decimal import Decimal

from bot.services.dedup import compute_dedup_key
from bot.services.schemas import ReceiptItemData, ReceiptVisionResponse


def _vision(
    *,
    fiscal_id: str | None = None,
    shop: str | None = "Магнум",
    total: str = "100.00",
) -> ReceiptVisionResponse:
    return ReceiptVisionResponse(
        shop_name=shop,
        total_amount=Decimal(total),
        fiscal_id=fiscal_id,
        items=[
            ReceiptItemData(
                name="Хлеб",
                quantity=Decimal(1),
                unit_price=Decimal("100.00"),
                total_price=Decimal("100.00"),
            )
        ],
    )


def test_fiscal_key_is_used_when_present() -> None:
    # Separators/spaces are stripped; the fiscal id keys the receipt.
    key = compute_dedup_key(7, _vision(fiscal_id="123-456 789"))
    assert key == "7:f:123456789"


def test_same_fiscal_same_key_across_uploads() -> None:
    a = compute_dedup_key(7, _vision(fiscal_id="123456"))
    b = compute_dedup_key(7, _vision(fiscal_id="123456", total="999.99"))
    assert a == b  # fiscal id alone identifies the receipt


def test_fallback_fingerprint_without_fiscal() -> None:
    key = compute_dedup_key(7, _vision())
    assert key.startswith("7:h:")


def test_per_family_keys_differ() -> None:
    k7 = compute_dedup_key(7, _vision(fiscal_id="123"))
    k8 = compute_dedup_key(8, _vision(fiscal_id="123"))
    assert k7 != k8


def test_fingerprint_changes_with_total() -> None:
    a = compute_dedup_key(7, _vision(total="100.00"))
    b = compute_dedup_key(7, _vision(total="200.00"))
    assert a != b
