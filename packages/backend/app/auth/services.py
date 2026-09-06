import secrets
from typing import Any
from uuid import UUID

from sqlalchemy import sql

from app.auth.errors import (
    CreditsLockExpiredError,
    InsufficientCreditsError,
    InvalidInviteCodeError,
)
from app.auth.models import TGInviteCode, TGUser
from app.conf import settings
from app.core.errors import AppError
from app.core.services import BaseService
from app.credits.models import CreditsTxStatus, TGUserCreditsTx
from app.models.base import utc_now
from app.tgbot.schemas import UserTGData


class TGUserService(BaseService):
    async def create(
        self, user_data: UserTGData, *, invite_code: str | None = None
    ) -> TGUser:
        if settings.TGBOT_REQUIRES_INVITE and not invite_code:
            raise InvalidInviteCodeError("Signup without invite code is disabled")

        async with self.tx():
            if settings.TGBOT_REQUIRES_INVITE:
                # check if invite code is valid
                invite_result = await self.db_session.execute(
                    sql.select(TGInviteCode).filter_by(code=invite_code)
                )
                tg_invite_code = invite_result.scalar_one_or_none()
                if not tg_invite_code:
                    raise InvalidInviteCodeError("Invite code isn't found")

                # decrement the invite code uses left
                if tg_invite_code.uses_left <= 0:
                    raise InvalidInviteCodeError("Invite code has no uses left")
                tg_invite_code.uses_left -= 1
            result = await self.db_session.execute(
                sql.insert(TGUser).values(**user_data.model_dump()).returning(TGUser)
            )
        return result.scalar_one()

    async def get_user(self, tg_user_id: int) -> TGUser | None:
        async with self.tx():
            result = await self.db_session.execute(
                sql.select(TGUser).filter_by(tg_id=tg_user_id)
            )
            tg_user = result.scalar_one_or_none()
        return tg_user

    async def get_user_and_update(
        self,
        user_data: UserTGData,
    ) -> TGUser | None:
        async with self.tx():
            result = await self.db_session.execute(
                sql.select(TGUser).filter_by(tg_id=user_data.tg_id)
            )
            tg_user = result.scalar_one_or_none()

            if not tg_user:
                return None

            # update
            if diff := tg_user.get_diff(user_data):
                result = await self.db_session.execute(
                    sql.update(TGUser)
                    .filter_by(tg_id=user_data.tg_id)
                    .values(**diff)
                    .returning(TGUser)
                )
                tg_user = result.scalar_one()

        return tg_user

    async def update_user(self, tg_user_id: int, **values: Any) -> TGUser:
        async with self.tx():
            result = await self.db_session.execute(
                sql.update(TGUser)
                .filter_by(tg_id=tg_user_id)
                .values(**values)
                .returning(TGUser)
            )
        return result.scalar_one()

    async def mark_bot_blocked(self, tg_user_id: int) -> bool:
        """
        Returns True only on the first transition to bot-blocked.
        """
        async with self.tx():
            result = await self.db_session.execute(
                sql.update(TGUser)
                .filter_by(tg_id=tg_user_id, is_bot_blocked=False)
                .values(is_bot_blocked=True)
                .returning(TGUser.tg_id)
            )
        return result.scalar_one_or_none() is not None

    async def mark_bot_unblocked(self, tg_user_id: int) -> bool:
        """
        Returns True only on the transition from bot-blocked back to reachable.
        """
        async with self.tx():
            result = await self.db_session.execute(
                sql.update(TGUser)
                .filter_by(tg_id=tg_user_id, is_bot_blocked=True)
                .values(is_bot_blocked=False)
                .returning(TGUser.tg_id)
            )
        return result.scalar_one_or_none() is not None

    async def list_users(
        self,
        limit: int,
        *,
        after_tg_id: int | None = None,
        exclude_banned: bool = False,
        exclude_bot_blocked: bool = False,
    ) -> list[TGUser]:
        """
        Keyset pagination by tg_id: pass the last seen tg_id to get the next
        page. Stable under concurrent inserts/deletes, unlike OFFSET.
        """
        query = sql.select(TGUser).order_by(TGUser.tg_id).limit(limit)
        if after_tg_id is not None:
            query = query.filter(TGUser.tg_id > after_tg_id)
        if exclude_banned:
            query = query.filter_by(is_banned=False)
        if exclude_bot_blocked:
            query = query.filter_by(is_bot_blocked=False)
        async with self.tx():
            result = await self.db_session.execute(query)
        return list(result.scalars().all())

    async def count_users(self) -> int:
        async with self.tx():
            result = await self.db_session.execute(
                sql.select(sql.func.count(TGUser.tg_id))
            )
        return result.scalar_one()

    async def add_credits(self, tg_user_id: int, amount: int) -> TGUser:
        async with self.tx():
            result = await self.db_session.execute(
                sql.update(TGUser)
                .filter_by(tg_id=tg_user_id)
                .values(credits_balance=TGUser.credits_balance + amount)
                .returning(TGUser)
            )
            tg_user = result.scalar_one()
        return tg_user

    async def lock_credits(self, tg_user_id: int, amount: int) -> UUID:
        lock_tx: TGUserCreditsTx | None = None
        async with self.tx():
            if await self.has_credits(tg_user_id):
                lock_tx = TGUserCreditsTx(
                    tg_user_id=tg_user_id, amount=amount, status=CreditsTxStatus.LOCKED
                )
                self.db_session.add(lock_tx)
                await self.db_session.execute(
                    sql.update(TGUser)
                    .filter_by(tg_id=tg_user_id)
                    .values(credits_balance=TGUser.credits_balance - amount)
                )
        if lock_tx is None:
            raise InsufficientCreditsError
        return lock_tx.id

    async def unlock_credits(self, tg_user_id: int, locked_tx_id: UUID) -> None:
        unlocked = False
        async with self.tx():
            lock_result = await self.db_session.execute(
                sql.select(TGUserCreditsTx).filter_by(
                    id=locked_tx_id,
                    tg_user_id=tg_user_id,
                    status=CreditsTxStatus.LOCKED,
                    deleted_at=None,
                )
            )
            lock_tx = lock_result.scalar_one_or_none()
            if lock_tx is not None:
                lock_tx.deleted_at = utc_now()
                await self.db_session.execute(
                    sql.update(TGUser)
                    .filter_by(tg_id=tg_user_id)
                    .values(credits_balance=TGUser.credits_balance + lock_tx.amount)
                )
                unlocked = True
        if not unlocked:
            raise CreditsLockExpiredError(
                f"Locked credits transaction is not found: '{locked_tx_id}'"
            )

    async def confirm_locked_credits(self, tg_user_id: int, locked_tx_id: UUID) -> None:
        error: AppError | None = None
        async with self.tx():
            if not await self.has_credits(tg_user_id):
                error = InsufficientCreditsError()
            else:
                lock_result = await self.db_session.execute(
                    sql.select(TGUserCreditsTx).filter_by(
                        id=locked_tx_id,
                        tg_user_id=tg_user_id,
                        status=CreditsTxStatus.LOCKED,
                        deleted_at=None,
                    )
                )
                lock_tx = lock_result.scalar_one_or_none()
                if lock_tx is None:
                    error = CreditsLockExpiredError(
                        f"Locked credits transaction is not found: '{locked_tx_id}'"
                    )
                else:
                    lock_tx.deleted_at = utc_now()
        if error is not None:
            raise error

    async def has_credits(self, tg_user_id: int) -> bool:
        async with self.tx():
            result = await self.db_session.execute(
                sql.select(TGUser.credits_balance).filter_by(tg_id=tg_user_id)
            )
        credit = result.scalar_one()
        return credit > 0


class TGInviteCodesService(BaseService):
    async def create(
        self,
        *,
        amount: int,
        uses: int,
        tg_user_id: int | None = None,
        is_created_by_admin: bool = False,
    ) -> list[TGInviteCode]:
        if amount > 10:
            raise AppError("Amount must be less than 10")
        if uses > 100:
            raise AppError("Uses must be less than 100")
        if uses < 1:
            raise AppError("Uses must be greater than 0")

        async with self.tx():
            now = utc_now()
            values = [
                {
                    "code": secrets.token_urlsafe(16),
                    "tg_user_id": tg_user_id,
                    "uses_left": uses,
                    "created_at": now,
                    "is_created_by_admin": is_created_by_admin,
                }
                for _ in range(amount)
            ]
            result = await self.db_session.execute(
                sql.insert(TGInviteCode).values(values).returning(TGInviteCode)
            )
        return list(result.scalars().all())
