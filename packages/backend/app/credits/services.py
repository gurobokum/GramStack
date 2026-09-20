from collections import defaultdict
from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager, suppress
from dataclasses import dataclass
from datetime import timedelta
from uuid import UUID

from sqlalchemy import sql
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.models import TGUser
from app.core.errors import AppError
from app.core.services import BaseService
from app.credits.errors import CreditsLockExpiredError, InsufficientCreditsError
from app.credits.models import (
    CreditsPurchase,
    CreditsPurchaseStatus,
    CreditsTx,
    CreditsTxStatus,
    StarsPurchaseMetadata,
)
from app.credits.schemas import CreditsPackage
from app.models.base import utc_now


@dataclass(frozen=True, slots=True)
class ExpiredCredits:
    count: int
    total: int


class CreditsService(BaseService):
    async def add_credits(self, tg_user_id: int, amount: int) -> int:
        async with self.tx():
            result = await self.db_session.execute(
                sql.update(TGUser)
                .filter_by(tg_id=tg_user_id)
                .values(credits_balance=TGUser.credits_balance + amount)
                .returning(TGUser.credits_balance)
            )
        return result.scalar_one()

    async def confirm_locked_credits(self, tg_user_id: int, locked_tx_id: UUID) -> None:
        async with self.tx():
            result = await self.db_session.execute(
                sql.update(CreditsTx)
                .filter_by(
                    id=locked_tx_id,
                    tg_user_id=tg_user_id,
                    status=CreditsTxStatus.LOCKED,
                )
                .values(status=CreditsTxStatus.CONFIRMED)
                .returning(CreditsTx.id)
            )
            if result.scalar_one_or_none() is None:
                raise CreditsLockExpiredError(
                    f"Locked credits transaction is not found: '{locked_tx_id}'"
                )

    async def expire_locked_credits(self, older_than: timedelta) -> ExpiredCredits:
        """
        Reclaim locks left behind by dead workers: flip stale LOCKED transactions
        to EXPIRED and refund their amounts. Claiming the rows in one guarded
        UPDATE is what makes this safe to run concurrently and safe to re-run - a
        second sweep matches nothing.
        """
        expired_count = 0
        async with self.tx():
            result = await self.db_session.execute(
                sql.update(CreditsTx)
                .filter(
                    CreditsTx.status == CreditsTxStatus.LOCKED,
                    CreditsTx.created_at < utc_now() - older_than,
                )
                .values(status=CreditsTxStatus.EXPIRED)
                .returning(CreditsTx.tg_user_id, CreditsTx.amount)
            )

            refunds: defaultdict[int, int] = defaultdict(int)
            for tg_user_id, amount in result.all():
                expired_count += 1
                # tg_user_id is nullable (ondelete SET NULL) - such a row is
                # expired but has nothing left to refund.
                if tg_user_id is not None:
                    refunds[tg_user_id] += amount

            for tg_user_id, amount in refunds.items():
                await self.db_session.execute(
                    sql.update(TGUser)
                    .filter_by(tg_id=tg_user_id)
                    .values(credits_balance=TGUser.credits_balance + amount)
                )

        return ExpiredCredits(count=expired_count, total=sum(refunds.values()))

    async def get_balance(self, tg_user_id: int) -> int:
        async with self.tx():
            result = await self.db_session.execute(
                sql.select(TGUser.credits_balance).filter_by(tg_id=tg_user_id)
            )
        return result.scalar_one()

    async def has_credits(self, tg_user_id: int) -> bool:
        return await self.get_balance(tg_user_id) > 0

    async def lock_credits(self, tg_user_id: int, amount: int) -> UUID:
        lock_tx: CreditsTx | None = None
        async with self.tx():
            result = await self.db_session.execute(
                sql.update(TGUser)
                .filter_by(tg_id=tg_user_id)
                .filter(TGUser.credits_balance >= amount)
                .values(credits_balance=TGUser.credits_balance - amount)
                .returning(TGUser.tg_id)
            )
            if result.scalar_one_or_none() is not None:
                lock_tx = CreditsTx(
                    tg_user_id=tg_user_id, amount=amount, status=CreditsTxStatus.LOCKED
                )
                self.db_session.add(lock_tx)
                await self.db_session.flush()

        if lock_tx is None:
            raise InsufficientCreditsError
        return lock_tx.id

    async def unlock_credits(self, tg_user_id: int, locked_tx_id: UUID) -> None:
        async with self.tx():
            result = await self.db_session.execute(
                sql.update(CreditsTx)
                .filter_by(
                    id=locked_tx_id,
                    tg_user_id=tg_user_id,
                    status=CreditsTxStatus.LOCKED,
                )
                .values(status=CreditsTxStatus.CANCELED)
                .returning(CreditsTx.amount)
            )
            amount = result.scalar_one_or_none()
            if amount is None:
                raise CreditsLockExpiredError(
                    f"Locked credits transaction is not found: '{locked_tx_id}'"
                )

            await self.db_session.execute(
                sql.update(TGUser)
                .filter_by(tg_id=tg_user_id)
                .values(credits_balance=TGUser.credits_balance + amount)
            )


@asynccontextmanager
async def spend_credits(
    db_session: AsyncSession,
    tg_user_id: int,
    amount: int | None = None,
    *,
    lock_tx_id: UUID | None = None,
) -> AsyncGenerator[UUID]:
    credits_svc = CreditsService(db_session)
    owns_lock = lock_tx_id is None
    if lock_tx_id is None:
        if amount is None:
            raise ValueError("Either amount or lock_tx_id is required")
        lock_tx_id = await credits_svc.lock_credits(tg_user_id, amount)

    try:
        yield lock_tx_id
    except Exception:
        if owns_lock:
            # A lock the sweeper already reclaimed must not mask why the work failed.
            with suppress(CreditsLockExpiredError):
                await credits_svc.unlock_credits(tg_user_id, lock_tx_id)
        raise
    if owns_lock:
        await credits_svc.confirm_locked_credits(tg_user_id, lock_tx_id)


class CreditsPurchaseService(BaseService):
    async def get_purchase(self, purchase_id: UUID) -> CreditsPurchase | None:
        async with self.tx():
            result = await self.db_session.execute(
                sql.select(CreditsPurchase).filter_by(id=purchase_id)
            )
        return result.scalar_one_or_none()

    async def init_credits_purchase(
        self, tg_user_id: int, package: CreditsPackage
    ) -> CreditsPurchase:
        async with self.tx():
            result = await self.db_session.execute(
                sql.insert(CreditsPurchase)
                .values(
                    tg_user_id=tg_user_id,
                    credits_amount=package.credits_amount,
                    package_name=package.package_name,
                    metadata_=StarsPurchaseMetadata(
                        package_name=package.package_name,
                        stars_amount=package.stars_amount,
                    ),
                )
                .returning(CreditsPurchase)
            )
        return result.scalar_one()

    async def confirm_purchase(self, purchase_id: UUID) -> CreditsPurchase:
        async with self.tx():
            result = await self.db_session.execute(
                sql.update(CreditsPurchase)
                .filter_by(id=purchase_id, status=CreditsPurchaseStatus.INITIAL)
                .values(status=CreditsPurchaseStatus.CONFIRMED)
                .returning(CreditsPurchase)
            )
        return result.scalar_one()

    async def complete_purchase(
        self,
        purchase_id: UUID,
        provider_payment_charge_id: str,
        telegram_payment_charge_id: str,
    ) -> CreditsPurchase:
        credits_svc = CreditsService(self.db_session)

        async with self.tx():
            purchase = await self.get_purchase(purchase_id)

            if not purchase:
                raise AppError("Purchase not found")

            if not purchase.tg_user_id:
                raise AppError("Purchase is orphaned")

            metadata = StarsPurchaseMetadata.model_validate(
                {
                    **purchase.metadata_.model_dump(),
                    "telegram_payment_charge_id": telegram_payment_charge_id,
                    "provider_payment_charge_id": provider_payment_charge_id,
                }
            )

            await credits_svc.add_credits(purchase.tg_user_id, purchase.credits_amount)
            result = await self.db_session.execute(
                sql.update(CreditsPurchase)
                .filter_by(id=purchase_id, status=CreditsPurchaseStatus.CONFIRMED)
                .values(status=CreditsPurchaseStatus.COMPLETED, metadata_=metadata)
                .returning(CreditsPurchase)
            )
        return result.scalar_one()
