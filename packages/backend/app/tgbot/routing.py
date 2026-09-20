"""
Redis-backed conversation state ("page") for bot handlers.

A handler can return a page string - it is saved per user in redis and loaded
into `context.page` on that user's next update. Every domain module exports a
`Handlers` bundle, and `register` wires them all: commands and callbacks per
domain, plus the bot's single free-text `MessageHandler` that dispatches
`messages` routes by the user's current page. Handlers registered directly on
the application do not take part in page tracking.
"""

import re
from collections.abc import Callable, Coroutine, Sequence
from dataclasses import dataclass, field
from typing import Any, Final, NewType

from telegram import Update
from telegram.ext import (
    BaseHandler,
    CallbackQueryHandler,
    ChatMemberHandler,
    CommandHandler,
    MessageHandler,
    filters,
)

from app.auth.services import TGUserService
from app.core.errors import AppError
from app.core.redis import RedisKey
from app.tgbot.app import TGApp
from app.tgbot.context import Context
from app.tgbot.utils import extract_user_data

PAGE_TTL: Final = 60 * 60 * 24 * 7

Page = NewType("Page", str)

type Handler = Callable[..., Coroutine[Any, Any, str | None]]


class Route:
    def __init__(self, pattern: str, handler: Handler) -> None:
        self.handler = handler
        self._regex = re.compile(pattern)

    def matches(self, page: str) -> bool:
        return self._regex.match(page) is not None

    def overlaps(self, other: "Route") -> bool:
        """
        True when the two patterns can match the same page, so the first
        registered route would shadow the other.
        """
        prefix, exact = self._literal_prefix()
        other_prefix, other_exact = other._literal_prefix()
        if exact and other_exact:
            return prefix == other_prefix
        if exact:
            return prefix.startswith(other_prefix)
        if other_exact:
            return other_prefix.startswith(prefix)
        return prefix.startswith(other_prefix) or other_prefix.startswith(prefix)

    def _literal_prefix(self) -> tuple[str, bool]:
        pattern = self._regex.pattern.removeprefix("^")
        exact = pattern.endswith("$")
        literal = re.split(r"[\\\[\](){}.*+?|^$]", pattern, maxsplit=1)[0]
        return literal, exact


def router(routes: Sequence[Route]) -> Handler:
    """
    Build a handler that dispatches the update to the first route whose
    pattern matches the user's current page. Does nothing when the user
    has no page or no route matches.
    """

    async def handle(update: Update, context: Context) -> str | None:
        page = context.page
        if page is None:
            return None

        for route in routes:
            if route.matches(page):
                return await route.handler(update, context)
        return None

    return handle


def track_page(handler: Handler) -> Handler:
    """
    Load the user's page from redis into `context.page` before the handler
    runs and save the page the handler returns. The stored page is consumed
    either way, so a handler returning None ends the conversation.
    """

    async def wrapper(update: Update, context: Context) -> str | None:
        user = update.effective_user
        key = RedisKey.PAGE.key(user.id) if user else None
        if key:
            raw = await context.redis.getdel(key)
            context.page = raw.decode() if isinstance(raw, bytes) else raw

        page = await handler(update, context)

        if key and page is not None:
            await context.redis.set(key, page, ex=PAGE_TTL)
        return None

    return wrapper


@dataclass
class Handlers:
    """
    One domain's bot handlers. `messages` holds page `Route`s, not PTB
    handlers - `register` merges them all into the bot's single free-text
    `MessageHandler`. `admin_only=True` gates every handler and route so
    they run only for admins.
    """

    commands: list[CommandHandler[Any, Any]] = field(default_factory=list)
    callbacks: list[CallbackQueryHandler[Any, Any]] = field(default_factory=list)
    messages: list[Route] = field(default_factory=list)
    payments: list[BaseHandler[Any, Any, Any]] = field(default_factory=list)
    chat_members: list[ChatMemberHandler[Any, Any]] = field(default_factory=list)
    admin_only: bool = False


def admin_gate(handler: Handler) -> Handler:
    """
    Run the handler only for admins; non-admin updates are dropped silently
    so the admin surface stays invisible. `TGAdminUser` injection in the
    handlers is for data access - this gate is the security check.
    """

    async def wrapper(update: Update, context: Context) -> str | None:
        user_data = extract_user_data(update)
        if not user_data:
            return context.page

        async with context.db_session_maker() as db_session:
            user = await TGUserService(db_session).get_user(user_data.tg_id)
        if not user or not user.is_admin:
            # track_page runs outside this gate and has already consumed
            # the user's page - return it so it gets saved back
            return context.page

        return await handler(update, context)

    return wrapper


def register(tg_app: TGApp, *domains: Handlers) -> None:
    """
    Wire all domains' handlers into the application: commands, callbacks,
    payment and chat-member handlers per domain, then one shared free-text
    `MessageHandler` built from every domain's `messages` routes. Raises on
    overlapping route patterns (the router runs the first match, so an
    overlap silently shadows a route) and on an `admin_only` domain whose
    callback or route patterns miss the `admin:` prefix.
    """
    routes: list[Route] = []
    for domain in domains:
        handlers: list[BaseHandler[Any, Any, Any]] = [
            *domain.commands,
            *domain.callbacks,
            *domain.payments,
            *domain.chat_members,
        ]
        if domain.admin_only:
            for callback in domain.callbacks:
                if not isinstance(callback.pattern, re.Pattern):
                    raise AppError(
                        f"Admin-only callback requires a regex pattern: {callback}"
                    )
                if not callback.pattern.pattern.startswith("^admin:"):
                    raise AppError(
                        "Admin-only callback pattern must start with '^admin:': "
                        f"'{callback.pattern.pattern}'"
                    )
            for route in domain.messages:
                if not route._regex.pattern.startswith("^admin:"):
                    raise AppError(
                        "Admin-only route pattern must start with '^admin:': "
                        f"'{route._regex.pattern}'"
                    )
                route.handler = admin_gate(route.handler)
            for handler in handlers:
                handler.callback = admin_gate(handler.callback)

        add_handlers(tg_app, handlers)
        routes.extend(domain.messages)

    for i, route in enumerate(routes):
        for other in routes[i + 1 :]:
            if route.overlaps(other):
                raise AppError(
                    "Route patterns overlap: "
                    f"'{route._regex.pattern}' and '{other._regex.pattern}'"
                )

    message_handler = MessageHandler(
        (filters.TEXT | filters.PHOTO) & ~filters.COMMAND,
        router(routes),
    )
    add_handlers(tg_app, [message_handler])


def add_handlers(
    tg_app: TGApp, *handler_lists: Sequence[BaseHandler[Any, Any, Any]]
) -> None:
    """
    Register handlers with page tracking enabled. `register` calls this for
    every domain; use it directly only for handlers outside a `Handlers`
    bundle.
    """
    for handlers in handler_lists:
        for handler in handlers:
            handler.callback = track_page(handler.callback)
        tg_app.add_handlers(handlers)
