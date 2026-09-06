from datetime import timedelta
from uuid import UUID

import pytest
from sqlalchemy import sql

from app.auth.errors import CreditsLockExpiredError
from app.auth.services import ExpiredCredits, TGUserService
from app.credits.models import CreditsTxStatus, TGUserCreditsTx
from app.db import AsyncSessionMaker
from app.models.base import utc_now
from tests.auth.test_credits_locks import TG_USER_ID, create_user, get_balance

TTL = timedelta(minutes=30)


async def backdate_lock(
    session_maker: AsyncSessionMaker, lock_tx_id: UUID, age: timedelta
) -> None:
    async with session_maker() as session, session.begin():
        await session.execute(
            sql.update(TGUserCreditsTx)
            .filter_by(id=lock_tx_id)
            .values(created_at=utc_now() - age)
        )


async def test_expire_refunds_stale_lock(db_session_maker: AsyncSessionMaker) -> None:
    await create_user(db_session_maker, credits=10)

    async with db_session_maker() as session:
        lock_tx_id = await TGUserService(session).lock_credits(TG_USER_ID, 3)
    await backdate_lock(db_session_maker, lock_tx_id, timedelta(hours=1))

    async with db_session_maker() as session:
        expired = await TGUserService(session).expire_locked_credits(TTL)

    assert expired == ExpiredCredits(count=1, total=3)
    assert await get_balance(db_session_maker) == 10

    async with db_session_maker() as session, session.begin():
        result = await session.execute(
            sql.select(TGUserCreditsTx.status, TGUserCreditsTx.deleted_at).filter_by(
                id=lock_tx_id
            )
        )
        status, deleted_at = result.one()
    assert status == CreditsTxStatus.EXPIRED
    assert deleted_at is not None


async def test_expire_skips_fresh_locks(db_session_maker: AsyncSessionMaker) -> None:
    await create_user(db_session_maker, credits=10)

    async with db_session_maker() as session:
        user_svc = TGUserService(session)
        await user_svc.lock_credits(TG_USER_ID, 3)
        expired = await user_svc.expire_locked_credits(TTL)

    assert expired == ExpiredCredits(count=0, total=0)
    assert await get_balance(db_session_maker) == 7


async def test_expire_second_sweep_matches_nothing(
    db_session_maker: AsyncSessionMaker,
) -> None:
    await create_user(db_session_maker, credits=10)

    async with db_session_maker() as session:
        lock_tx_id = await TGUserService(session).lock_credits(TG_USER_ID, 3)
    await backdate_lock(db_session_maker, lock_tx_id, timedelta(hours=1))

    async with db_session_maker() as session:
        user_svc = TGUserService(session)
        await user_svc.expire_locked_credits(TTL)
        expired = await user_svc.expire_locked_credits(TTL)

    assert expired == ExpiredCredits(count=0, total=0)
    assert await get_balance(db_session_maker) == 10


async def test_confirm_after_expire_raises(db_session_maker: AsyncSessionMaker) -> None:
    await create_user(db_session_maker, credits=10)

    async with db_session_maker() as session:
        lock_tx_id = await TGUserService(session).lock_credits(TG_USER_ID, 3)
    await backdate_lock(db_session_maker, lock_tx_id, timedelta(hours=1))

    async with db_session_maker() as session:
        user_svc = TGUserService(session)
        await user_svc.expire_locked_credits(TTL)
        with pytest.raises(CreditsLockExpiredError):
            await user_svc.confirm_locked_credits(TG_USER_ID, lock_tx_id)
