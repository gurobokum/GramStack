from pathlib import Path

import structlog
from dishka import FromDishka, Provider, Scope, provide
from telegram import Update

from app.auth.models import TGUser
from app.core.errors import AppError
from app.core.utils import load_yaml
from app.tgbot.i18n._generated import HandlersTexts as HandlersTexts
from app.tgbot.utils import (
    LocalizedTexts,
    extract_user_data,
    get_texts,
    resolve_language,
)

logger = structlog.get_logger()

type Language = str

LANGUAGE_LABELS = {
    "ru": "Русский 🇷🇺",
    "en": "English 🇬🇧",
}


class Texts(LocalizedTexts[HandlersTexts]):
    en: HandlersTexts
    ru: HandlersTexts


try:
    TEXTS: Texts = load_yaml(
        Path(__file__).parent / "texts.yaml", Texts, key="handlers"
    )
except Exception:
    logger.error("Failed to load tgbot i18n texts")
    raise


class TGBotI18NProvider(Provider):
    """
    Requires a root provider that supplies Update.
    """

    @provide(scope=Scope.REQUEST)
    def get_language(
        self, update: FromDishka[Update], tg_user: FromDishka[TGUser | None]
    ) -> Language:
        if tg_user and tg_user.language:
            return tg_user.language

        user_data = extract_user_data(update)
        if user_data is None:
            chat = update.effective_chat
            raise AppError("User data is None", chat_id=chat.id if chat else None)
        return resolve_language(user_data.language_code)

    @provide(scope=Scope.REQUEST)
    def get_handlers_texts(self, lang: FromDishka[Language]) -> HandlersTexts:
        return get_texts(TEXTS, lang)
