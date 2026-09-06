import enum

from pydantic import BaseModel
from sqlalchemy import BigInteger, CheckConstraint, ForeignKey, Index
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import PydanticJSON, RecordModel, ValueEnum


class CreditsTxStatus(str, enum.Enum):
    LOCKED = "locked"
    EXPIRED = "expired"


class TGUserCreditsTx(RecordModel):
    __tablename__ = "tg_user_credits_transactions"
    __table_args__ = (
        CheckConstraint(
            "amount > 0", name="tg_user_credits_transactions__amount_positive"
        ),
        Index("ix_tg_user_credits_transactions__deleted_at", "deleted_at"),
        Index(
            "ix_tg_user_credits_transactions__hanging_transactions",
            "created_at",
            "deleted_at",
            "status",
        ),
    )

    amount: Mapped[int] = mapped_column(BigInteger, nullable=False)
    status: Mapped[CreditsTxStatus] = mapped_column(
        ValueEnum(CreditsTxStatus, name="tg_user_credits_transaction_status"),
        default=CreditsTxStatus.LOCKED,
        nullable=False,
    )

    # Foreign keys
    tg_user_id: Mapped[int | None] = mapped_column(
        ForeignKey("tg_users.tg_id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )


class CreditsPurchaseStatus(str, enum.Enum):
    INITIAL = "initial"
    CONFIRMED = "confirmed"
    COMPLETED = "completed"


class StarsPurchaseMetadata(BaseModel):
    telegram_payment_charge_id: str | None = None
    provider_payment_charge_id: str | None = None
    stars_amount: int
    package_name: str


class TGUserCreditsPurchase(RecordModel):
    __tablename__ = "tg_user_credits_purchases"
    __table_args__ = (
        Index(
            "ix_tg_user_credits_transactions__hanging_purchases",
            "status",
            "created_at",
        ),
    )

    credits_amount: Mapped[int] = mapped_column(BigInteger, nullable=False)
    package_name: Mapped[str] = mapped_column(nullable=False)

    metadata_: Mapped[StarsPurchaseMetadata] = mapped_column(
        "metadata",
        PydanticJSON(StarsPurchaseMetadata, none_as_null=True),
        nullable=True,
    )
    status: Mapped[CreditsPurchaseStatus] = mapped_column(
        ValueEnum(CreditsPurchaseStatus, name="tg_user_credits_purchase_status"),
        default=CreditsPurchaseStatus.INITIAL,
        nullable=False,
    )

    # Foreign keys
    tg_user_id: Mapped[int | None] = mapped_column(
        ForeignKey("tg_users.tg_id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
