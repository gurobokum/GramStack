from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager
from uuid import UUID

from sqlalchemy import sql
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.services import TGUserService
from app.core.errors import AppError
from app.core.services import BaseService
from app.credits.models import (
    CreditsPurchaseStatus,
    StarsPurchaseMetadata,
    TGUserCreditsPurchase,
)
from app.credits.schemas import CreditsPackage


@asynccontextmanager
async def spend_credits(
    db_session: AsyncSession,
    tg_user_id: int,
    amount: int | None = None,
    *,
    lock_tx_id: UUID | None = None,
) -> AsyncGenerator[UUID]:
    tg_user_svc = TGUserService(db_session)
    if lock_tx_id is None:
        if amount is None:
            raise ValueError("Either amount or lock_tx_id is required")
        lock_tx_id = await tg_user_svc.lock_credits(tg_user_id, amount)
    try:
        yield lock_tx_id
    except Exception:
        await tg_user_svc.unlock_credits(tg_user_id, lock_tx_id)
        raise
    await tg_user_svc.confirm_locked_credits(tg_user_id, lock_tx_id)


class TGUserCreditsService(BaseService):
    async def get_purchase(self, purchase_id: UUID) -> TGUserCreditsPurchase | None:
        async with self.tx():
            result = await self.db_session.execute(
                sql.select(TGUserCreditsPurchase).filter_by(id=purchase_id)
            )
        return result.scalar_one()

    async def init_credits_purchase(
        self, tg_user_id: int, package: CreditsPackage
    ) -> TGUserCreditsPurchase:
        async with self.tx():
            result = await self.db_session.execute(
                sql.insert(TGUserCreditsPurchase)
                .values(
                    tg_user_id=tg_user_id,
                    credits_amount=package.credits_amount,
                    package_name=package.package_name,
                    metadata_=StarsPurchaseMetadata(
                        package_name=package.package_name,
                        stars_amount=package.stars_amount,
                    ),
                )
                .returning(TGUserCreditsPurchase)
            )
        return result.scalar_one()

    async def confirm_purchase(self, purchase_id: UUID) -> TGUserCreditsPurchase:
        async with self.tx():
            result = await self.db_session.execute(
                sql.update(TGUserCreditsPurchase)
                .filter_by(id=purchase_id, status=CreditsPurchaseStatus.INITIAL)
                .values(status=CreditsPurchaseStatus.CONFIRMED)
                .returning(TGUserCreditsPurchase)
            )
        return result.scalar_one()

    async def complete_purchase(
        self,
        purchase_id: UUID,
        provider_payment_charge_id: str,
        telegram_payment_charge_id: str,
    ) -> TGUserCreditsPurchase:
        user_svc = TGUserService(self.db_session)

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

            await user_svc.add_credits(purchase.tg_user_id, purchase.credits_amount)
            result = await self.db_session.execute(
                sql.update(TGUserCreditsPurchase)
                .filter_by(id=purchase_id, status=CreditsPurchaseStatus.CONFIRMED)
                .values(status=CreditsPurchaseStatus.COMPLETED, metadata_=metadata)
                .returning(TGUserCreditsPurchase)
            )
        return result.scalar_one()
