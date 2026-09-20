from collections.abc import AsyncIterator
from functools import partial
from typing import Any, cast

from dishka import Provider, Scope, from_context, make_async_container, provide
from redis.asyncio import Redis as AsyncRedis
from sqlalchemy.ext.asyncio import AsyncSession
from telegram import Chat, Message, Update

from app.auth.models import TGAdminUser, TGUser
from app.auth.services import TGUserService
from app.core.errors import AppError, ForbiddenError, UserIsBannedError
from app.credits.i18n import TGBotCreditsI18NProvider
from app.dishka import ServicesProvider
from app.dishka import inject as inject_factory
from app.posthog import PostHogEvent, posthog
from app.tgbot.admin.i18n import TGBotAdminI18NProvider
from app.tgbot.context import Context
from app.tgbot.i18n import TGBotI18NProvider
from app.tgbot.routing import Page
from app.tgbot.utils import extract_user_data


class TGBotRootProvider(Provider):
    update = from_context(provides=Update, scope=Scope.REQUEST)
    context = from_context(provides=Context, scope=Scope.REQUEST)

    @provide(scope=Scope.REQUEST)
    async def get_db_session(self, context: Context) -> AsyncIterator[AsyncSession]:
        async with context.db_session_maker() as db_session:
            yield db_session

    @provide(scope=Scope.REQUEST)
    def get_redis(self, context: Context) -> AsyncRedis:
        if not context.redis:
            raise AppError("Redis is None")
        return context.redis

    @provide(scope=Scope.REQUEST)
    def get_chat(self, update: Update) -> Chat:
        chat = update.effective_chat
        if not chat:
            raise AppError("Chat is None")
        return chat

    @provide(scope=Scope.REQUEST)
    def get_query_message(self, update: Update) -> Message:
        if not update.callback_query:
            raise AppError("Callback query is None")

        message = update.callback_query.message
        if not message:
            raise AppError("Message is None")
        if not message.is_accessible:
            raise AppError("Message is not accessible")

        return cast(Message, message)

    @provide(scope=Scope.REQUEST)
    def get_page(self, context: Context) -> Page:
        if context.page is None:
            raise AppError("Page is None")
        return Page(context.page)

    @provide(scope=Scope.REQUEST)
    async def get_user(self, update: Update, db_session: AsyncSession) -> TGUser | None:
        user_data = extract_user_data(update)
        if not user_data:
            return None
        return await TGUserService(db_session).get_user_and_update(user_data)

    @provide(scope=Scope.REQUEST)
    def signin_user(self, tg_user: TGUser | None) -> TGUser:
        if not tg_user:
            raise ForbiddenError("User not found")
        if tg_user.is_banned:
            raise UserIsBannedError

        posthog.set(
            distinct_id=str(tg_user.tg_id), properties={"username": tg_user.username}
        )
        return tg_user

    @provide(scope=Scope.REQUEST)
    def signin_admin_user(self, tg_user: TGUser) -> TGAdminUser:
        if not tg_user.is_admin:
            raise ForbiddenError("User is not admin", tg_user_id=tg_user.tg_id)
        return cast(TGAdminUser, tg_user)


tg_container = make_async_container(
    TGBotRootProvider(),
    ServicesProvider(),
    TGBotI18NProvider(),
    TGBotCreditsI18NProvider(),
    TGBotAdminI18NProvider(),
)


def provide_context(args: tuple[Any, ...], _: dict[str, Any]) -> dict[Any, Any]:
    return {
        Update: args[0],
        Context: args[1],
    }


inject = partial(inject_factory, tg_container, provide_context)
