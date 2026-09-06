from uuid import UUID, uuid4

import pytest
from sqlalchemy import sql

from app.auth.models import TGUser
from app.auth.services import TGUserService
from app.credits.errors import CreditsLockExpiredError, InsufficientCreditsError
from app.credits.models import CreditsTx, CreditsTxStatus
from app.credits.services import CreditsService, spend_credits
from app.db import AsyncSessionMaker
from app.tgbot.schemas import UserTGData

TG_USER_ID = 100


async def create_user(
    session_maker: AsyncSessionMaker, tg_id: int = TG_USER_ID, credits: int = 0
) -> TGUser:
    async with session_maker() as session:
        user = await TGUserService(session).create(
            UserTGData.model_validate({"id": tg_id, "username": f"user{tg_id}"})
        )
        if credits:
            await CreditsService(session).add_credits(tg_id, credits)
    return user


async def get_balance(session_maker: AsyncSessionMaker, tg_id: int = TG_USER_ID) -> int:
    async with session_maker() as session:
        return await CreditsService(session).get_balance(tg_id)


async def get_tx_status(
    session_maker: AsyncSessionMaker, lock_tx_id: UUID
) -> CreditsTxStatus:
    async with session_maker() as session, session.begin():
        result = await session.execute(
            sql.select(CreditsTx.status).filter_by(id=lock_tx_id)
        )
        return result.scalar_one()


async def test_add_credits_returns_balance(db_session_maker: AsyncSessionMaker) -> None:
    await create_user(db_session_maker)

    async with db_session_maker() as session:
        balance = await CreditsService(session).add_credits(TG_USER_ID, 10)

    assert balance == 10


async def test_lock_credits_reduces_balance(
    db_session_maker: AsyncSessionMaker,
) -> None:
    await create_user(db_session_maker, credits=10)

    async with db_session_maker() as session:
        lock_tx_id = await CreditsService(session).lock_credits(TG_USER_ID, 3)

    assert await get_balance(db_session_maker) == 7
    assert await get_tx_status(db_session_maker, lock_tx_id) == CreditsTxStatus.LOCKED


async def test_lock_credits_without_balance_keeps_session_usable(
    db_session_maker: AsyncSessionMaker,
) -> None:
    await create_user(db_session_maker)

    async with db_session_maker() as session:
        credits_svc = CreditsService(session)
        with pytest.raises(InsufficientCreditsError):
            await credits_svc.lock_credits(TG_USER_ID, 3)
        balance = await credits_svc.get_balance(TG_USER_ID)

    assert balance == 0


async def test_lock_credits_more_than_balance(
    db_session_maker: AsyncSessionMaker,
) -> None:
    await create_user(db_session_maker, credits=2)

    async with db_session_maker() as session:
        with pytest.raises(InsufficientCreditsError):
            await CreditsService(session).lock_credits(TG_USER_ID, 3)

    assert await get_balance(db_session_maker) == 2


async def test_confirm_locked_credits(db_session_maker: AsyncSessionMaker) -> None:
    await create_user(db_session_maker, credits=10)

    async with db_session_maker() as session:
        credits_svc = CreditsService(session)
        lock_tx_id = await credits_svc.lock_credits(TG_USER_ID, 3)
        await credits_svc.confirm_locked_credits(TG_USER_ID, lock_tx_id)

    assert await get_balance(db_session_maker) == 7
    assert (
        await get_tx_status(db_session_maker, lock_tx_id) == CreditsTxStatus.CONFIRMED
    )


async def test_unlock_credits_refunds(db_session_maker: AsyncSessionMaker) -> None:
    await create_user(db_session_maker, credits=10)

    async with db_session_maker() as session:
        credits_svc = CreditsService(session)
        lock_tx_id = await credits_svc.lock_credits(TG_USER_ID, 3)
        await credits_svc.unlock_credits(TG_USER_ID, lock_tx_id)

    assert await get_balance(db_session_maker) == 10
    assert await get_tx_status(db_session_maker, lock_tx_id) == CreditsTxStatus.CANCELED


async def test_confirm_missing_lock_raises_expired(
    db_session_maker: AsyncSessionMaker,
) -> None:
    await create_user(db_session_maker, credits=10)

    async with db_session_maker() as session:
        with pytest.raises(CreditsLockExpiredError):
            await CreditsService(session).confirm_locked_credits(TG_USER_ID, uuid4())


async def test_unlock_missing_lock_raises_expired(
    db_session_maker: AsyncSessionMaker,
) -> None:
    await create_user(db_session_maker, credits=10)

    async with db_session_maker() as session:
        with pytest.raises(CreditsLockExpiredError):
            await CreditsService(session).unlock_credits(TG_USER_ID, uuid4())


async def test_confirm_already_confirmed_lock_raises_expired(
    db_session_maker: AsyncSessionMaker,
) -> None:
    await create_user(db_session_maker, credits=10)

    async with db_session_maker() as session:
        credits_svc = CreditsService(session)
        lock_tx_id = await credits_svc.lock_credits(TG_USER_ID, 3)
        await credits_svc.confirm_locked_credits(TG_USER_ID, lock_tx_id)
        with pytest.raises(CreditsLockExpiredError):
            await credits_svc.confirm_locked_credits(TG_USER_ID, lock_tx_id)


async def test_spend_credits_confirms_on_success(
    db_session_maker: AsyncSessionMaker,
) -> None:
    await create_user(db_session_maker, credits=10)

    async with (
        db_session_maker() as session,
        spend_credits(session, TG_USER_ID, 3) as lock_tx_id,
    ):
        assert isinstance(lock_tx_id, UUID)

    assert await get_balance(db_session_maker) == 7
    assert (
        await get_tx_status(db_session_maker, lock_tx_id) == CreditsTxStatus.CONFIRMED
    )


async def test_spend_credits_refunds_on_error(
    db_session_maker: AsyncSessionMaker,
) -> None:
    await create_user(db_session_maker, credits=10)

    async with db_session_maker() as session:
        with pytest.raises(RuntimeError):
            async with spend_credits(session, TG_USER_ID, 3):
                raise RuntimeError

    assert await get_balance(db_session_maker) == 10


async def test_spend_credits_does_not_finalize_borrowed_lock(
    db_session_maker: AsyncSessionMaker,
) -> None:
    await create_user(db_session_maker, credits=10)

    async with db_session_maker() as session:
        lock_tx_id = await CreditsService(session).lock_credits(TG_USER_ID, 3)
        async with spend_credits(session, TG_USER_ID, lock_tx_id=lock_tx_id) as yielded:
            assert yielded == lock_tx_id

    assert await get_balance(db_session_maker) == 7
    assert await get_tx_status(db_session_maker, lock_tx_id) == CreditsTxStatus.LOCKED


async def test_spend_credits_requires_amount_or_lock(
    db_session_maker: AsyncSessionMaker,
) -> None:
    await create_user(db_session_maker, credits=10)

    async with db_session_maker() as session:
        with pytest.raises(ValueError):
            async with spend_credits(session, TG_USER_ID):
                pass
