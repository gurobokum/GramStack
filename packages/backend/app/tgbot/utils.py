from collections.abc import Awaitable, Sequence
from typing import Any, Generic, TypeVar, cast

import structlog
from pydantic import BaseModel
from telegram import (
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    LinkPreviewOptions,
    Message,
    MessageEntity,
    Update,
    WebAppInfo,
)
from telegram.error import BadRequest, Forbidden

from app.auth.services import TGUserService
from app.posthog import PostHogEvent, posthog
from app.tgbot.context import Context
from app.tgbot.schemas import UserTGData

logger = structlog.get_logger()

SUPPORTED_LANGUAGES = ("en", "ru")
# Post-Soviet language codes default to Russian; the Baltics stay on English.
RU_DEFAULT_LANGUAGE_CODES = frozenset(
    {"az", "be", "hy", "ka", "kk", "ky", "tg", "tk", "uk", "uz"}
)


async def send_or_mark_blocked(
    user_svc: TGUserService, tg_user_id: int, send: Awaitable[Any]
) -> bool:
    """
    Await a send call; on Forbidden (user blocked the bot) mark the user
    is_bot_blocked=True and return False instead of raising. The posthog event
    fires only on the first transition, so retries stay quiet.
    """
    try:
        await send
    except Forbidden:
        if await user_svc.mark_bot_blocked(tg_user_id):
            posthog.capture(tg_user_id, PostHogEvent.USER_BLOCKED_BOT)
        return False
    return True


async def edit_page(
    message: Message,
    text: str,
    markup: InlineKeyboardMarkup | None,
    link_preview_options: LinkPreviewOptions | None = None,
    entities: Sequence[MessageEntity] | None = None,
) -> None:
    """
    Edit a self-updating menu message in place. The "message is not
    modified" error a Refresh-style edit produces is ignored; on any other
    edit failure the page is sent as a new message instead.
    """
    try:
        await message.edit_text(
            text=text,
            reply_markup=markup,
            link_preview_options=link_preview_options,
            entities=entities,
        )
    except BadRequest as e:
        if "not modified" in str(e).lower():
            return
        logger.warning("Failed to edit the message, sending a new one", error=str(e))
        await message.chat.send_message(
            text=text,
            reply_markup=markup,
            link_preview_options=link_preview_options,
            entities=entities,
        )


type KeyboardButton = tuple[str, str | WebAppInfo]


def keyboard(*args: Sequence[KeyboardButton | None]) -> InlineKeyboardMarkup:
    """
    Build an InlineKeyboardMarkup from rows of (label, target) tuples.

    A str target becomes callback_data, a WebAppInfo target becomes a web app
    button. None entries and empty rows are skipped, so call sites can pass
    conditional buttons inline.
    """
    keyboard_markup = []

    for arg in args:
        row = []
        for button in arg:
            if not button:
                continue
            if isinstance(button[1], WebAppInfo):
                row.append(InlineKeyboardButton(button[0], web_app=button[1]))
            else:
                row.append(InlineKeyboardButton(button[0], callback_data=button[1]))

        if not row:
            continue
        keyboard_markup.append(row)

    return InlineKeyboardMarkup(keyboard_markup)


def extract_user_data(update: Update) -> UserTGData | None:
    try:
        user = next(
            getattr(update, attr)
            for attr in [
                "message",
                "edited_message",
                "inline_query",
                "chosen_inline_result",
                "callback_query",
                "poll",
                "poll_answer",
                "pre_checkout_query",
            ]
            if hasattr(update, attr) and getattr(update, attr) is not None
        ).from_user
    except StopIteration:
        return None

    return UserTGData.model_validate_json(user.to_json())


T = TypeVar("T", bound=BaseModel)


class LocalizedTexts(BaseModel, Generic[T]):
    en: T
    ru: T


def resolve_language(language_code: str) -> str:
    if language_code in SUPPORTED_LANGUAGES:
        return language_code
    if language_code in RU_DEFAULT_LANGUAGE_CODES:
        return "ru"
    return "en"


def get_texts(texts: LocalizedTexts[T], lang: str) -> T:
    bundle = getattr(texts, resolve_language(lang))
    if not bundle:
        raise ValueError(f"Language {lang} not found in bundle")
    return cast(T, bundle)


def get_invite_code(context: Context) -> str | None:
    if not context or not context.args:
        return None

    payload = context.args[0]
    return str(payload).split("&")[0].strip()
