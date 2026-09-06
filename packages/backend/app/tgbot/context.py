from typing import Any

from arq.connections import ArqRedis
from redis.asyncio import Redis as AsyncRedis
from sqlalchemy.ext.asyncio import AsyncSession
from telegram.ext import CallbackContext, ExtBot

from app.auth.models import TGUser
from app.db import AsyncSessionMaker


class Context(
    CallbackContext[ExtBot[None], dict[Any, Any], dict[Any, Any], dict[Any, Any]]
):
    db_session_maker: AsyncSessionMaker
    arq: ArqRedis
    redis: AsyncRedis

    db_session: AsyncSession | None = None
    tg_user: TGUser | None = None
    page: str | None = None
