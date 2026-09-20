from typing import NewType

from sqlalchemy import BigInteger, CheckConstraint, ForeignKey
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import PostgresUUID, TimestampModel, string_column
from app.tgbot.schemas import UserTGData


class TGUser(TimestampModel):
    __tablename__ = "tg_users"
    __table_args__ = (
        CheckConstraint(
            "credits_balance >= 0", name="tg_users__credits_balance_positive"
        ),
    )

    tg_id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    username: Mapped[str] = string_column(64)
    first_name: Mapped[str] = string_column(64)
    last_name: Mapped[str] = string_column(64)
    phone: Mapped[str] = string_column(64)
    language_code: Mapped[str] = string_column(8)
    language: Mapped[str] = string_column(8)

    is_bot: Mapped[bool] = mapped_column(nullable=False, default=False)
    is_banned: Mapped[bool] = mapped_column(nullable=False, default=False)
    is_bot_blocked: Mapped[bool] = mapped_column(nullable=False, default=False)
    is_admin: Mapped[bool] = mapped_column(nullable=False, default=False)

    credits_balance: Mapped[int] = mapped_column(default=0, server_default="0")

    # Foreign keys
    invite_code: Mapped[str] = mapped_column(
        ForeignKey("tg_invite_codes.code"), nullable=True
    )

    def get_diff(self, user_data: UserTGData) -> dict[str, str | bool]:
        """
        Compare the current object with the provided user_data and return a dictionary of differences.
        """
        if self.tg_id != user_data.tg_id:
            raise ValueError("tg_id does not match between the two objects.")

        diff = {}
        for field in user_data.model_fields_set:
            if getattr(self, field) != getattr(user_data, field):
                diff[field] = getattr(user_data, field)
        return diff


TGAdminUser = NewType("TGAdminUser", TGUser)


class TGInviteCode(TimestampModel):
    __tablename__ = "tg_invite_codes"

    code: Mapped[str] = string_column(primary_key=True)
    uses_left: Mapped[int] = mapped_column(default=1)
    is_created_by_admin: Mapped[bool] = mapped_column(default=False)

    # Foreign keys
    tg_user_id = mapped_column(
        BigInteger, ForeignKey("tg_users.tg_id"), nullable=True, index=True
    )
