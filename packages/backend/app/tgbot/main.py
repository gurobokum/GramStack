from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager

import structlog
from arq.connections import create_pool
from redis.asyncio import Redis as AsyncRedis
from telegram import BotCommand, Update
from telegram.ext import ApplicationHandlerStop, TypeHandler

from app.conf import settings
from app.core.errors import ForbiddenError, UserIsBannedError
from app.credits.errors import InsufficientCreditsError
from app.credits.handlers import handlers as credits_handlers
from app.db import AsyncSessionMaker
from app.posthog import PostHogEvent, posthog
from app.tgbot.app import TGApp, tg_app
from app.tgbot.context import Context
from app.tgbot.handlers import handlers, signin_middleware
from app.tgbot.i18n import TEXTS
from app.tgbot.routing import add_handlers
from app.tgbot.utils import extract_user_data, get_texts
from app.worker.conf import WorkerSettings

logger = structlog.get_logger()


async def error_handler(update: object, context: Context) -> None:
    error = context.error

    if not isinstance(update, Update):
        logger.exception("Exception while handling update:", exc_info=error)
        return

    user_data = extract_user_data(update)
    chat = update.effective_chat
    texts = get_texts(TEXTS, user_data.language_code) if user_data else TEXTS.en

    if isinstance(error, UserIsBannedError):
        if chat:
            await chat.send_message(text=texts.error_handler.banned_text)
        raise ApplicationHandlerStop

    if isinstance(error, InsufficientCreditsError) and user_data:
        posthog.capture(user_data.tg_id, PostHogEvent.NO_CREDITS)

    # Show welcome message to user if he is not authorized
    if isinstance(error, ForbiddenError) and chat:
        await chat.send_message(text=texts.start.welcome_text)

    logger.exception("Exception while handling update:", exc_info=error)


@asynccontextmanager
async def start_tg_app(session_maker: AsyncSessionMaker) -> AsyncGenerator[TGApp]:
    # The middleware stays outside add_handlers: page tracking there would
    # consume the stored page before the group-0 handler sees it.
    tg_app.add_handler(TypeHandler(Update, signin_middleware), group=-1)
    add_handlers(tg_app, handlers, credits_handlers)
    tg_app.add_error_handler(error_handler)

    if settings.TGBOT_SETUP_COMMANDS:
        await setup_commands(tg_app)
    if settings.TGBOT_WEBHOOK_URL and settings.TGBOT_WEBHOOK_SECRET_TOKEN:
        await tg_app.bot.set_webhook(
            settings.TGBOT_WEBHOOK_URL,
            secret_token=settings.TGBOT_WEBHOOK_SECRET_TOKEN.get_secret_value(),
        )
        logger.info(f"Telegram webhook is set as {settings.TGBOT_WEBHOOK_URL}")

    Context.db_session_maker = session_maker
    Context.arq = await create_pool(
        WorkerSettings.redis_settings, default_queue_name=WorkerSettings.queue_name
    )
    Context.redis = AsyncRedis.from_url(settings.REDIS_URL.get_secret_value())

    async with tg_app:
        if tg_app.post_init is not None:
            await tg_app.post_init(tg_app)

        if tg_app.updater is not None:
            await tg_app.updater.start_polling()
            logger.info("Telegram bot polling started")

        await tg_app.start()
        logger.info("Telegram bot started")

        yield tg_app

        await Context.arq.aclose()
        await Context.redis.aclose()
        if tg_app.updater is not None:
            await tg_app.updater.stop()
        await tg_app.stop()
        if tg_app.post_stop is not None:
            await tg_app.post_stop(tg_app)
    if tg_app.post_shutdown is not None:
        await tg_app.post_shutdown(tg_app)


async def setup_commands(tg_app: TGApp) -> None:
    commands = {
        "en": {
            "start": "start",
        },
        "ru": {
            "start": "старт",
        },
    }
    # localize
    for lang in ["en", "ru"]:
        commands_lang = commands[lang]
        await tg_app.bot.set_my_commands(
            [BotCommand(k, v) for k, v in commands_lang.items()],
            language_code=lang,
        )
