from typing import ClassVar

from sqlalchemy import sql

from app.db import AsyncSessionMaker
from app.tgbot.models import Config
from app.tgbot.schemas import BaseConfig
from app.tgbot.services import ConfigService

FILE_IDS = ["AgACAgIAAxkBAAO1", "AgACAgIAAxkBAAO2"]


class StartPhotosConfig(BaseConfig):
    config_name: ClassVar[str] = "start_photos"

    file_ids: list[str] = []


async def count_configs(session_maker: AsyncSessionMaker) -> int:
    async with session_maker() as session, session.begin():
        result = await session.execute(sql.select(sql.func.count(Config.id)))
    return result.scalar_one()


async def test_get_config_returns_defaults(
    db_session_maker: AsyncSessionMaker,
) -> None:
    async with db_session_maker() as session:
        config = await ConfigService(session).get_config(StartPhotosConfig)

    assert config == StartPhotosConfig(file_ids=[])


async def test_set_config_round_trips(db_session_maker: AsyncSessionMaker) -> None:
    async with db_session_maker() as session:
        svc = ConfigService(session)
        stored = await svc.set_config(StartPhotosConfig(file_ids=FILE_IDS))

    assert stored.name == "start_photos"
    assert stored.data == {"file_ids": FILE_IDS}

    async with db_session_maker() as session:
        config = await ConfigService(session).get_config(StartPhotosConfig)
    assert config.file_ids == FILE_IDS


async def test_set_config_updates_in_place(
    db_session_maker: AsyncSessionMaker,
) -> None:
    async with db_session_maker() as session:
        svc = ConfigService(session)
        await svc.set_config(StartPhotosConfig(file_ids=FILE_IDS))
        await svc.set_config(StartPhotosConfig(file_ids=FILE_IDS[:1]))

    assert await count_configs(db_session_maker) == 1

    async with db_session_maker() as session:
        config = await ConfigService(session).get_config(StartPhotosConfig)
    assert config.file_ids == FILE_IDS[:1]
