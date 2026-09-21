import secrets
from typing import Any, Literal, overload

from sqlalchemy import sql

from app.auth.errors import InvalidInviteCodeError
from app.auth.models import TGInviteCode, TGUser
from app.conf import settings
from app.core.errors import AppError, NotFoundError
from app.core.services import BaseService
from app.models.base import utc_now
from app.tgbot.schemas import UserTGData


class TGUserService(BaseService):
    async def create(
        self, user_data: UserTGData, *, invite_code: str | None = None
    ) -> TGUser:
        if settings.TGBOT_REQUIRES_INVITE and not invite_code:
            raise InvalidInviteCodeError("Signup without invite code is disabled")

        async with self.tx():
            values: dict[str, Any] = user_data.model_dump()
            tg_invite_code = (
                await self._redeem_invite_code(invite_code) if invite_code else None
            )
            if tg_invite_code:
                values["redeemed_invite_code"] = tg_invite_code.code
                values["inviter_id"] = tg_invite_code.tg_user_id

            result = await self.db_session.execute(
                sql.insert(TGUser).values(**values).returning(TGUser)
            )
        return result.scalar_one()

    async def _redeem_invite_code(self, code: str) -> TGInviteCode | None:
        """
        Spend one use of the code. An unusable code raises only when invites are
        required, otherwise the user signs up without an inviter.
        """
        result = await self.db_session.execute(
            sql.select(TGInviteCode).filter_by(code=code)
        )
        tg_invite_code = result.scalar_one_or_none()

        if tg_invite_code is None:
            if settings.TGBOT_REQUIRES_INVITE:
                raise InvalidInviteCodeError(f"Invite code isn't found: '{code}'")
            return None

        if tg_invite_code.uses_left <= 0:
            if settings.TGBOT_REQUIRES_INVITE:
                raise InvalidInviteCodeError(f"Invite code has no uses left: '{code}'")
            return None

        tg_invite_code.uses_left -= 1
        return tg_invite_code

    @overload
    async def get_user(self, tg_user_id: int, *, required: Literal[True]) -> TGUser: ...

    @overload
    async def get_user(
        self, tg_user_id: int, *, required: Literal[False] = False
    ) -> TGUser | None: ...

    async def get_user(
        self, tg_user_id: int, *, required: bool = False
    ) -> TGUser | None:
        async with self.tx():
            result = await self.db_session.execute(
                sql.select(TGUser).filter_by(tg_id=tg_user_id)
            )
            tg_user = result.scalar_one_or_none()
        if required and tg_user is None:
            raise NotFoundError(f"User is not found: '{tg_user_id}'")
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
