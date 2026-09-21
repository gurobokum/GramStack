import pytest
from pytest import MonkeyPatch
from sqlalchemy import sql

from app.auth.errors import InvalidInviteCodeError
from app.auth.models import TGInviteCode
from app.auth.services import TGInviteCodesService, TGUserService
from app.conf import settings
from app.db import AsyncSessionMaker
from app.tgbot.schemas import UserTGData

INVITER_ID = 200
INVITED_ID = 201


async def create_invite(
    session_maker: AsyncSessionMaker, *, uses: int = 1, tg_user_id: int = INVITER_ID
) -> str:
    async with session_maker() as session:
        await TGUserService(session).create(
            UserTGData.model_validate({"id": tg_user_id, "username": "inviter"})
        )
        invites = await TGInviteCodesService(session).create(
            amount=1, uses=uses, tg_user_id=tg_user_id
        )
    return invites[0].code


async def get_uses_left(session_maker: AsyncSessionMaker, code: str) -> int:
    async with session_maker() as session, session.begin():
        result = await session.execute(
            sql.select(TGInviteCode.uses_left).filter_by(code=code)
        )
        return result.scalar_one()


async def spend_all_uses(session_maker: AsyncSessionMaker, code: str) -> None:
    async with session_maker() as session, session.begin():
        await session.execute(
            sql.update(TGInviteCode).filter_by(code=code).values(uses_left=0)
        )


async def signup(
    session_maker: AsyncSessionMaker, code: str | None
) -> tuple[str | None, int | None]:
    async with session_maker() as session:
        user = await TGUserService(session).create(
            UserTGData.model_validate({"id": INVITED_ID, "username": "invited"}),
            invite_code=code,
        )
    return user.redeemed_invite_code, user.inviter_id


async def test_signup_records_inviter(db_session_maker: AsyncSessionMaker) -> None:
    code = await create_invite(db_session_maker)

    assert await signup(db_session_maker, code) == (code, INVITER_ID)


async def test_signup_spends_one_use(db_session_maker: AsyncSessionMaker) -> None:
    code = await create_invite(db_session_maker, uses=2)
    await signup(db_session_maker, code)

    assert await get_uses_left(db_session_maker, code) == 1


async def test_signup_without_code_has_no_inviter(
    db_session_maker: AsyncSessionMaker,
) -> None:
    assert await signup(db_session_maker, None) == (None, None)


async def test_unknown_code_is_ignored_when_invites_optional(
    db_session_maker: AsyncSessionMaker,
) -> None:
    assert await signup(db_session_maker, "nope") == (None, None)


async def test_unknown_code_raises_when_invites_required(
    db_session_maker: AsyncSessionMaker, monkeypatch: MonkeyPatch
) -> None:
    monkeypatch.setattr(settings, "TGBOT_REQUIRES_INVITE", True)

    with pytest.raises(InvalidInviteCodeError):
        await signup(db_session_maker, "nope")


async def test_spent_code_raises_when_invites_required(
    db_session_maker: AsyncSessionMaker, monkeypatch: MonkeyPatch
) -> None:
    code = await create_invite(db_session_maker)
    await spend_all_uses(db_session_maker, code)
    monkeypatch.setattr(settings, "TGBOT_REQUIRES_INVITE", True)

    with pytest.raises(InvalidInviteCodeError):
        await signup(db_session_maker, code)


async def test_signup_without_code_raises_when_invites_required(
    db_session_maker: AsyncSessionMaker, monkeypatch: MonkeyPatch
) -> None:
    monkeypatch.setattr(settings, "TGBOT_REQUIRES_INVITE", True)

    with pytest.raises(InvalidInviteCodeError):
        await signup(db_session_maker, None)
