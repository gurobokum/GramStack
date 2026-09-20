from pathlib import Path

import structlog
from dishka import FromDishka, Provider, Scope, provide

from app.core.utils import load_yaml
from app.tgbot.admin.i18n._generated import HandlersTexts as HandlersTexts
from app.tgbot.i18n import Language
from app.tgbot.utils import LocalizedTexts, get_texts

logger = structlog.get_logger()


class Texts(LocalizedTexts[HandlersTexts]):
    en: HandlersTexts
    ru: HandlersTexts


try:
    TEXTS: Texts = load_yaml(
        Path(__file__).parent / "texts.yaml", Texts, key="handlers"
    )
except Exception:
    logger.error("Failed to load admin i18n texts")
    raise


class TGBotAdminI18NProvider(Provider):
    """
    Requires TGBotI18NProvider with Language.
    """

    @provide(scope=Scope.REQUEST)
    def get_admin_handlers_texts(self, lang: FromDishka[Language]) -> HandlersTexts:
        return get_texts(TEXTS, lang)
