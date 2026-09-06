from uuid import uuid4

import pytest

from app.auth.errors import CreditsLockExpiredError, InsufficientCreditsError
from app.auth.models import TGUser
from app.auth.services import TGUserService
from app.db import AsyncSessionMaker
from app.tgbot.schemas import UserTGData

TG_USER_ID = 100


async def create_user(
    session_maker: AsyncSessionMaker, tg_id: int = TG_USER_ID, credits: int = 0
) -> TGUser:
    async with session_maker() as session:
        user_svc = TGUserService(session)
        user = await user_svc.create(
            UserTGData.model_validate({"id": tg_id, "username": f"user{tg_id}"})
        )
        if credits:
            user = await user_svc.add_credits(tg_id, credits)
    return user


async def get_balance(session_maker: AsyncSessionMaker, tg_id: int = TG_USER_ID) -> int:
    async with session_maker() as session:
        user = await TGUserService(session).get_user(tg_id)
        assert user is not None
    return user.credits_balance


async def test_lock_credits_reduces_balance(
    db_session_maker: AsyncSessionMaker,
) -> None:
    await create_user(db_session_maker, credits=10)

    async with db_session_maker() as session:
        await TGUserService(session).lock_credits(TG_USER_ID, 3)

    assert await get_balance(db_session_maker) == 7


async def test_lock_credits_without_balance_keeps_session_usable(
    db_session_maker: AsyncSessionMaker,
) -> None:
    await create_user(db_session_maker)

    async with db_session_maker() as session:
        user_svc = TGUserService(session)
        with pytest.raises(InsufficientCreditsError):
            await user_svc.lock_credits(TG_USER_ID, 3)
        user = await user_svc.get_user(TG_USER_ID)

    assert user is not None
    assert user.credits_balance == 0


async def test_confirm_locked_credits(db_session_maker: AsyncSessionMaker) -> None:
    await create_user(db_session_maker, credits=10)

    async with db_session_maker() as session:
        user_svc = TGUserService(session)
        lock_tx_id = await user_svc.lock_credits(TG_USER_ID, 3)
        await user_svc.confirm_locked_credits(TG_USER_ID, lock_tx_id)

    assert await get_balance(db_session_maker) == 7


async def test_unlock_credits_refunds(db_session_maker: AsyncSessionMaker) -> None:
    await create_user(db_session_maker, credits=10)

    async with db_session_maker() as session:
        user_svc = TGUserService(session)
        lock_tx_id = await user_svc.lock_credits(TG_USER_ID, 3)
        await user_svc.unlock_credits(TG_USER_ID, lock_tx_id)

    assert await get_balance(db_session_maker) == 10


async def test_confirm_missing_lock_raises_expired(
    db_session_maker: AsyncSessionMaker,
) -> None:
    await create_user(db_session_maker, credits=10)

    async with db_session_maker() as session:
        with pytest.raises(CreditsLockExpiredError):
            await TGUserService(session).confirm_locked_credits(TG_USER_ID, uuid4())


async def test_unlock_missing_lock_raises_expired(
    db_session_maker: AsyncSessionMaker,
) -> None:
    await create_user(db_session_maker, credits=10)

    async with db_session_maker() as session:
        with pytest.raises(CreditsLockExpiredError):
            await TGUserService(session).unlock_credits(TG_USER_ID, uuid4())


async def test_confirm_already_confirmed_lock_raises_expired(
    db_session_maker: AsyncSessionMaker,
) -> None:
    await create_user(db_session_maker, credits=10)

    async with db_session_maker() as session:
        user_svc = TGUserService(session)
        lock_tx_id = await user_svc.lock_credits(TG_USER_ID, 3)
        await user_svc.confirm_locked_credits(TG_USER_ID, lock_tx_id)
        with pytest.raises(CreditsLockExpiredError):
            await user_svc.confirm_locked_credits(TG_USER_ID, lock_tx_id)
