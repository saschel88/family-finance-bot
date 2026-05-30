from __future__ import annotations

import asyncio
import signal
from collections.abc import Callable

import anthropic
from google import genai
from telegram.ext import (
    Application,
    ApplicationBuilder,
    CallbackQueryHandler,
    CommandHandler,
    ContextTypes,
    ConversationHandler,
    MessageHandler,
    filters,
)

from bot.core.config import Settings, get_settings
from bot.core.database import async_session, dispose_engine
from bot.core.logging import configure_logging, get_logger
from bot.db.models import Category
from bot.handlers import commands, receipt
from bot.handlers.commands import OnboardingState
from bot.services.classifier import Classifier, ClassifyFn
from bot.services.classify_gemini import GeminiClassifier
from bot.services.claude_classify import ClaudeClassifier
from bot.services.exchange import ExchangeService
from bot.services.nct import NctClient
from bot.services.ofd import OfdClient
from bot.services.receipt_text import (
    ClaudeReceiptParser,
    GeminiReceiptParser,
    ReceiptTextParser,
)
from bot.services.reporter import Reporter
from bot.services.vision import VisionService
from bot.services.vision_common import VisionEngine
from bot.services.vision_gemini import GeminiVisionService

logger = get_logger(__name__)

ClassifyFactory = Callable[[list[Category]], ClassifyFn]


def build_ai_services(
    settings: Settings,
) -> tuple[VisionEngine, ClassifyFactory, ReceiptTextParser]:
    """Construct the vision engine, a classify-factory, and the OFD-text parser
    for the configured provider (gemini | claude)."""
    if settings.ai_provider == "claude":
        client = anthropic.AsyncAnthropic(api_key=settings.anthropic_api_key)
        model = settings.anthropic_model
        vision: VisionEngine = VisionService(client, model)
        ofd_parser: ReceiptTextParser = ClaudeReceiptParser(client, model)

        def claude_factory(cats: list[Category]) -> ClassifyFn:
            return ClaudeClassifier(client, model, cats)

        logger.info("ai provider", provider="claude", model=model)
        return vision, claude_factory, ofd_parser

    gemini_client = genai.Client(api_key=settings.gemini_api_key)
    model = settings.gemini_model
    vision = GeminiVisionService(gemini_client, model)
    ofd_parser = GeminiReceiptParser(gemini_client, model)

    def gemini_factory(cats: list[Category]) -> ClassifyFn:
        return GeminiClassifier(gemini_client, model, cats)

    logger.info("ai provider", provider="gemini", model=model)
    return vision, gemini_factory, ofd_parser


def build_application() -> Application:  # type: ignore[type-arg]
    settings = get_settings()

    nct = NctClient(
        base_url=settings.nct_api_base_url,
        api_key=settings.nct_api_key,
        cache_ttl=settings.nct_cache_ttl,
    )
    exchange = ExchangeService(async_session, settings.nbk_api_url)
    vision, classify_factory, ofd_parser = build_ai_services(settings)
    classifier = Classifier(nct)
    reporter = Reporter(async_session)

    application = ApplicationBuilder().token(settings.telegram_bot_token).build()
    application.bot_data.update(
        {
            "session_factory": async_session,
            "vision": vision,
            "classify_factory": classify_factory,
            "ofd_client": OfdClient(),
            "ofd_parser": ofd_parser,
            "classifier": classifier,
            "exchange": exchange,
            "reporter": reporter,
            "nct": nct,
        }
    )

    onboarding = ConversationHandler(
        entry_points=[CommandHandler("start", commands.start)],
        states={
            OnboardingState.CHOOSING: [
                CallbackQueryHandler(commands.onboarding_choice, pattern="^onboard:")
            ],
            OnboardingState.WAITING_NAME: [
                MessageHandler(
                    filters.TEXT & ~filters.COMMAND, commands.onboarding_create
                )
            ],
            OnboardingState.WAITING_INVITE_TOKEN: [
                MessageHandler(
                    filters.TEXT & ~filters.COMMAND, commands.onboarding_join
                )
            ],
        },
        fallbacks=[CommandHandler("cancel", commands.cancel)],
    )

    application.add_handler(onboarding)
    application.add_handler(CommandHandler("invite", commands.invite))
    application.add_handler(CommandHandler("report", commands.report))
    application.add_handler(CommandHandler("categories", commands.categories))
    application.add_handler(CommandHandler("learn", commands.learn))
    application.add_handler(CommandHandler("rate", commands.rate))
    application.add_handler(MessageHandler(filters.PHOTO, receipt.photo_handler))
    application.add_handler(
        CallbackQueryHandler(receipt.category_callback, pattern="^cat:")
    )
    application.add_handler(
        CallbackQueryHandler(receipt.date_callback, pattern="^rdate:")
    )
    # Manual purchase-date capture runs in a separate group so it never
    # consumes text destined for the onboarding conversation.
    application.add_handler(
        MessageHandler(filters.TEXT & ~filters.COMMAND, receipt.date_text_handler),
        group=1,
    )
    application.add_error_handler(_error_handler)

    return application


async def _error_handler(update: object, context: ContextTypes.DEFAULT_TYPE) -> None:
    logger.error("unhandled error", error=str(context.error))


async def run() -> None:
    settings = get_settings()
    configure_logging(settings.log_level, settings.environment)

    application = build_application()
    stop_event = asyncio.Event()

    loop = asyncio.get_running_loop()
    for sig in (signal.SIGINT, signal.SIGTERM):
        try:
            loop.add_signal_handler(sig, stop_event.set)
        except NotImplementedError:  # pragma: no cover - Windows dev
            pass

    await application.initialize()
    await application.start()
    assert application.updater is not None
    await application.updater.start_polling()
    logger.info("bot started")

    try:
        await stop_event.wait()
    finally:
        logger.info("bot shutting down")
        if application.updater is not None:
            await application.updater.stop()
        await application.stop()
        await application.shutdown()
        await dispose_engine()


def main() -> None:
    asyncio.run(run())


if __name__ == "__main__":
    main()
