import pytest

from app.auth.services import TGUserService
from app.core.errors import NotFoundError
from app.db import AsyncSessionMaker
from tests.credits.test_credits_service import TG_USER_ID, create_user


async def test_get_user_returns_none_when_missing(
    db_session_maker: AsyncSessionMaker,
) -> None:
    async with db_session_maker() as session:
        user = await TGUserService(session).get_user(TG_USER_ID)

    assert user is None


async def test_get_user_required_raises_when_missing(
    db_session_maker: AsyncSessionMaker,
) -> None:
    async with db_session_maker() as session:
        with pytest.raises(NotFoundError):
            await TGUserService(session).get_user(TG_USER_ID, required=True)


async def test_get_user_required_returns_user(
    db_session_maker: AsyncSessionMaker,
) -> None:
    await create_user(db_session_maker)

    async with db_session_maker() as session:
        user = await TGUserService(session).get_user(TG_USER_ID, required=True)

    assert user.tg_id == TG_USER_ID
