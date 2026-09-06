"""
Redis-backed conversation state ("page") for bot handlers.

A handler can return a page string - it is saved per user in redis and loaded
into `context.page` on that user's next update. Free-text steps are registered
with `router([Route(pattern, handler), ...])` inside a `MessageHandler`: the
message goes to the first route whose pattern matches the user's current page.
Handlers must be registered through `add_handlers` - handlers added directly
to the application do not take part in page tracking.
"""

import re
from collections.abc import Callable, Coroutine, Sequence
from typing import Any, Final, NewType

from telegram import Update
from telegram.ext import BaseHandler

from app.tgbot.app import TGApp
from app.tgbot.context import Context

PAGE_TTL: Final = 60 * 60 * 24 * 7

Page = NewType("Page", str)

type Handler = Callable[..., Coroutine[Any, Any, str | None]]


def page_key(tg_user_id: int) -> str:
    return f"page:{tg_user_id}"


class Route:
    def __init__(self, pattern: str, handler: Handler) -> None:
        self.handler = handler
        self._regex = re.compile(pattern)

    def matches(self, page: str) -> bool:
        return self._regex.match(page) is not None


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
        key = page_key(user.id) if user else None
        if key:
            raw = await context.redis.getdel(key)
            context.page = raw.decode() if isinstance(raw, bytes) else raw

        page = await handler(update, context)

        if key and page is not None:
            await context.redis.set(key, page, ex=PAGE_TTL)
        return None

    return wrapper


def add_handlers(
    tg_app: TGApp, *handler_lists: Sequence[BaseHandler[Any, Any, Any]]
) -> None:
    """
    Register handlers with page tracking enabled. Use this instead of
    `tg_app.add_handlers` for every user-facing handler list.
    """
    for handlers in handler_lists:
        for handler in handlers:
            handler.callback = track_page(handler.callback)
        tg_app.add_handlers(handlers)
