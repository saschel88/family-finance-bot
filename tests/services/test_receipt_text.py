from __future__ import annotations

from decimal import Decimal

from bot.services.receipt_text import GeminiReceiptParser
from tests.conftest import make_gemini

_JSON = """
{
  "shop_name": "ТОО КАРИ КЗ",
  "purchased_at": "2026-05-01T18:53:32",
  "currency": "KZT",
  "total_amount": 26965.00,
  "fiscal_id": "841061549277",
  "items": [
    {"name": "Бэтэнке SN2 6SS-33A", "quantity": 1, "unit_price": 12243.00,
     "total_price": 12243.00, "barcode": "04630529181414",
     "ntin": "0200141815130"},
    {"name": "polybag_kari", "quantity": 1, "unit_price": 35.00,
     "total_price": 35.00, "barcode": null, "ntin": "0200145051817"}
  ]
}
"""


async def test_parse_ofd_text_into_structure() -> None:
    parser = GeminiReceiptParser(make_gemini(_JSON), ["gemini-test"])
    result = await parser.parse("exact receipt text from OFD")
    assert result.total_amount == Decimal("26965.00")
    assert result.fiscal_id == "841061549277"
    assert len(result.items) == 2
    assert result.items[0].barcode == "04630529181414"
    assert result.items[0].ntin == "0200141815130"
    # NTIN present even when GTIN is absent.
    assert result.items[1].barcode is None
    assert result.items[1].ntin == "0200145051817"
