from collections.abc import AsyncGenerator

import logfire
from arq.connections import ArqRedis
from fastapi import Request
from pydantic import SecretStr
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker
from sqlalchemy.ext.asyncio import create_async_engine as _create_async_engine

from app.conf import settings

type AsyncSessionMaker = async_sessionmaker[AsyncSession]


def create_async_engine(url: SecretStr, application_name: str) -> AsyncEngine:
    engine = _create_async_engine(
        url.get_secret_value(),
        echo=settings.DEBUG_SQL,
        pool_pre_ping=True,
        connect_args={"server_settings": {"application_name": application_name}},
    )
    if settings.LOGFIRE_TOKEN and settings.LOGFIRE_SQLALCHEMY:
        logfire.instrument_sqlalchemy(engine)
    return engine


def create_session_maker(engine: AsyncEngine) -> AsyncSessionMaker:
    return async_sessionmaker(
        engine,
        expire_on_commit=False,
        autobegin=False,
        autoflush=False,
    )


async def get_db_session(request: Request) -> AsyncGenerator[AsyncSession]:
    session_maker = request.state.session_maker
    async with session_maker() as db_session:
        yield db_session


async def get_arq(request: Request) -> AsyncGenerator[None, ArqRedis]:
    yield request.state.arq
