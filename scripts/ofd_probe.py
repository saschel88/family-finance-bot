#!/usr/bin/env python
"""Dev tool: discover an OFD's internal JSON API behind its consumer portal.

Many Kazakhstan OFD consumer pages are JavaScript SPAs that fetch the receipt
from an internal JSON endpoint. Rather than reverse-engineering each one by
hand in DevTools, this script opens the QR/consumer URL in a headless browser,
captures all XHR/fetch responses, and prints the ones that look like the
receipt API — giving you the exact endpoint + parameters to wire into
``bot/services/ofd.py`` (runtime still uses httpx, not a browser).

Usage:
    uv run playwright install chromium      # one-time
    uv run python scripts/ofd_probe.py "https://consumer.<ofd>.kz/?i=...&f=...&s=...&t=..."
    uv run python scripts/ofd_probe.py <url> --all      # dump every JSON response

This is a DEV helper — it is not imported by the bot and not shipped in the
Docker image.
"""

from __future__ import annotations

import argparse
import asyncio
import sys

from playwright.async_api import Response, async_playwright

# Structural tokens that a receipt JSON tends to contain.
_RECEIPT_HINTS = ("found", "ticketurl", "gtin", "ntin")
# Static assets / localization files to ignore.
_IGNORE_URL = ("/assets/", "/i18n/", "/locale", ".js", ".css")


def _looks_like_receipt(url: str, body: str) -> bool:
    low_url = url.lower()
    if any(part in low_url for part in _IGNORE_URL):
        return False
    low = body.lower()
    return any(hint in low for hint in _RECEIPT_HINTS)


async def probe(url: str, timeout_ms: int, dump_all: bool) -> int:
    captured: list[tuple[str, str, str]] = []  # (method, url, body)

    async with async_playwright() as pw:
        browser = await pw.chromium.launch(headless=True)
        page = await browser.new_page()
        pending: list[Response] = []
        page.on("response", lambda resp: pending.append(resp))
        try:
            await page.goto(url, wait_until="networkidle", timeout=timeout_ms)
        except Exception as exc:  # noqa: BLE001 - best-effort discovery
            print(f"[warn] navigation issue: {exc}", file=sys.stderr)
        await page.wait_for_timeout(2000)
        print(f"final page URL: {page.url}\n")
        for resp in pending:
            content_type = (resp.headers or {}).get("content-type", "")
            if "json" not in content_type.lower():
                continue
            try:
                body = await resp.text()
            except Exception:  # noqa: BLE001
                continue
            captured.append((resp.request.method, resp.url, body))
        await browser.close()

    receipts = [c for c in captured if _looks_like_receipt(c[1], c[2])]
    chosen = captured if dump_all else (receipts or captured)
    if not chosen:
        print("No JSON responses captured. Try --all or increase --timeout.")
        return 1

    print(f"Captured {len(captured)} JSON response(s); "
          f"{len(receipts)} look receipt-like.\n")
    for method, resp_url, body in chosen:
        flag = _looks_like_receipt(resp_url, body)
        marker = "  <-- LIKELY RECEIPT API" if flag else ""
        print("=" * 72)
        print(f"{method} {resp_url}{marker}")
        print("-" * 72)
        print(body[:1500])
        print()
    return 0


def main() -> None:
    parser = argparse.ArgumentParser(description="Discover an OFD JSON API.")
    parser.add_argument("url", help="OFD consumer/QR URL")
    parser.add_argument("--timeout", type=int, default=30000, help="ms")
    parser.add_argument(
        "--all", action="store_true", help="print every JSON response"
    )
    args = parser.parse_args()
    raise SystemExit(asyncio.run(probe(args.url, args.timeout, args.all)))


if __name__ == "__main__":
    main()
