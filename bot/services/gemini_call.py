from __future__ import annotations

import asyncio
from typing import Any

from google import genai
from google.genai import errors, types

from bot.core.logging import get_logger
from bot.services.gemini_retry import MAX_RETRIES, RETRYABLE_CODES, next_delay

logger = get_logger(__name__)


async def generate_with_fallback(
    client: genai.Client,
    models: list[str],
    *,
    contents: list[Any],
    config: types.GenerateContentConfig,
    label: str,
) -> types.GenerateContentResponse:
    """Call generate_content trying each model in order.

    On a retryable error (429/5xx) the next model is tried immediately — each
    free-tier model has its own quota, so a fallback often succeeds when the
    primary is rate-limited. Only when the whole chain is exhausted do we wait
    (honoring the server's retry hint) and retry the chain. Non-retryable
    errors propagate at once. Raises the last APIError if all attempts fail.
    """
    last_exc: errors.APIError | None = None
    for attempt in range(MAX_RETRIES):
        for model in models:
            try:
                return await client.aio.models.generate_content(
                    model=model, contents=contents, config=config
                )
            except errors.APIError as exc:
                if exc.code in RETRYABLE_CODES:
                    last_exc = exc
                    logger.warning(
                        f"{label} model failover",
                        model=model,
                        code=exc.code,
                    )
                    continue
                raise
        if last_exc is not None and attempt < MAX_RETRIES - 1:
            await asyncio.sleep(next_delay(last_exc, attempt))
    assert last_exc is not None
    raise last_exc
