from app.auth.services import TGUserService
from app.db import AsyncSessionMaker
from app.tgbot.handlers import lang, lang_set
from app.tgbot.i18n import LANGUAGE_LABELS, TEXTS
from app.tgbot.schemas import UserTGData
from tests.helpers.bot import bot_calls, make_offline_bot
from tests.helpers.updates import make_callback_update, make_context, make_update


async def create_user(
    db_session_maker: AsyncSessionMaker, user_id: int, language_code: str
) -> None:
    async with db_session_maker() as session:
        await TGUserService(session).create(
            UserTGData.model_validate(
                {
                    "id": user_id,
                    "username": f"testuser{user_id}",
                    "first_name": "Test",
                    "language_code": language_code,
                }
            )
        )


async def test_lang_shows_current_language(
    db_session_maker: AsyncSessionMaker,
) -> None:
    await create_user(db_session_maker, 4004, "ru")

    bot = await make_offline_bot()
    update = make_update(bot, text="/lang", user_id=4004, language_code="ru")
    context = make_context(bot, db_session_maker)

    await lang(update, context)

    endpoint, params = bot_calls(bot)[-1]
    assert endpoint == "sendMessage"
    assert params["text"] == f"{TEXTS.ru.lang.current_text} {LANGUAGE_LABELS['ru']}"
    buttons = [
        button for row in params["reply_markup"]["inline_keyboard"] for button in row
    ]
    assert [button["callback_data"] for button in buttons] == [
        "lang:set:ru",
        "lang:set:en",
    ]
    assert [button["text"] for button in buttons] == list(LANGUAGE_LABELS.values())


async def test_lang_resolves_ussr_language_code_to_russian(
    db_session_maker: AsyncSessionMaker,
) -> None:
    await create_user(db_session_maker, 5005, "kk")

    bot = await make_offline_bot()
    update = make_update(bot, text="/lang", user_id=5005, language_code="kk")
    context = make_context(bot, db_session_maker)

    await lang(update, context)

    endpoint, params = bot_calls(bot)[-1]
    assert endpoint == "sendMessage"
    assert params["text"] == f"{TEXTS.ru.lang.current_text} {LANGUAGE_LABELS['ru']}"


async def test_lang_resolves_unknown_language_code_to_english(
    db_session_maker: AsyncSessionMaker,
) -> None:
    await create_user(db_session_maker, 5006, "de")

    bot = await make_offline_bot()
    update = make_update(bot, text="/lang", user_id=5006, language_code="de")
    context = make_context(bot, db_session_maker)

    await lang(update, context)

    endpoint, params = bot_calls(bot)[-1]
    assert endpoint == "sendMessage"
    assert params["text"] == f"{TEXTS.en.lang.current_text} {LANGUAGE_LABELS['en']}"


async def test_lang_set_stores_language(
    db_session_maker: AsyncSessionMaker,
) -> None:
    await create_user(db_session_maker, 6006, "en")

    bot = await make_offline_bot()
    update = make_callback_update(bot, data="lang:set:ru", user_id=6006)
    context = make_context(bot, db_session_maker)

    await lang_set(update, context)

    async with db_session_maker() as session:
        user = await TGUserService(session).get_user(6006, required=True)
    assert user.language == "ru"

    calls = bot_calls(bot)
    answer_params = next(
        params for endpoint, params in calls if endpoint == "answerCallbackQuery"
    )
    assert (
        answer_params["text"]
        == f"{TEXTS.ru.lang.selected_text} {LANGUAGE_LABELS['ru']}"
    )

    endpoint, params = calls[-1]
    assert endpoint == "editMessageText"
    assert params["text"] == f"{TEXTS.ru.lang.current_text} {LANGUAGE_LABELS['ru']}"
