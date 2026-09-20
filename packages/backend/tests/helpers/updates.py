from typing import Any

from telegram import Update
from telegram.ext import Application, ApplicationBuilder, ContextTypes, ExtBot

from app.db import AsyncSessionMaker
from app.tgbot.context import Context
from tests.helpers.bot import TEST_BOT_ID


def make_update(
    bot: ExtBot[None],
    *,
    text: str = "/start",
    user_id: int = 1001,
    chat_id: int | None = None,
    language_code: str = "en",
    photo_file_id: str | None = None,
) -> Update:
    chat_id = chat_id if chat_id is not None else user_id
    message: dict[str, Any] = {
        "message_id": 1,
        "date": 1,
        "chat": {"id": chat_id, "type": "private"},
        "from": {
            "id": user_id,
            "is_bot": False,
            "first_name": "Test",
            "username": f"testuser{user_id}",
            "language_code": language_code,
        },
    }
    if photo_file_id is not None:
        message["photo"] = [
            {
                "file_id": photo_file_id,
                "file_unique_id": "u1",
                "width": 100,
                "height": 100,
            }
        ]
    else:
        entities: list[dict[str, Any]] = []
        if text.startswith("/"):
            entities.append(
                {"type": "bot_command", "offset": 0, "length": len(text.split()[0])}
            )
        message["text"] = text
        message["entities"] = entities
    return Update.de_json({"update_id": 1, "message": message}, bot)


def make_callback_update(
    bot: ExtBot[None],
    *,
    data: str,
    user_id: int = 1001,
    language_code: str = "en",
) -> Update:
    return Update.de_json(
        {
            "update_id": 3,
            "callback_query": {
                "id": "1",
                "chat_instance": "1",
                "from": {
                    "id": user_id,
                    "is_bot": False,
                    "first_name": "Test",
                    "username": f"testuser{user_id}",
                    "language_code": language_code,
                },
                "message": {
                    "message_id": 1,
                    "date": 1,
                    "chat": {"id": user_id, "type": "private"},
                    "text": "page",
                },
                "data": data,
            },
        },
        bot,
    )


def make_chat_member_update(
    bot: ExtBot[None], *, user_id: int = 1001, new_status: str = "kicked"
) -> Update:
    old_status = "member" if new_status == "kicked" else "kicked"
    user = {"id": user_id, "is_bot": False, "first_name": "Test"}
    bot_user = {"id": TEST_BOT_ID, "is_bot": True, "first_name": "Test Bot"}

    def member(status: str) -> dict[str, Any]:
        data: dict[str, Any] = {"user": bot_user, "status": status}
        if status == "kicked":
            data["until_date"] = 0
        return data

    return Update.de_json(
        {
            "update_id": 2,
            "my_chat_member": {
                "chat": {"id": user_id, "type": "private"},
                "from": user,
                "date": 1,
                "old_chat_member": member(old_status),
                "new_chat_member": member(new_status),
            },
        },
        bot,
    )


def make_context(bot: ExtBot[None], db_session_maker: AsyncSessionMaker) -> Context:
    application: Application[
        ExtBot[None], Context, dict[Any, Any], dict[Any, Any], dict[Any, Any], Any
    ] = (
        ApplicationBuilder()
        .bot(bot)
        .updater(None)
        .context_types(ContextTypes(context=Context))
        .build()
    )
    context = Context(application=application)
    context.db_session_maker = db_session_maker
    return context
