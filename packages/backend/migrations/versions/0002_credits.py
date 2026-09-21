"""credits

Revision ID: 0002
Revises: 0001
Create Date: 2026-09-20 17:41:00.000000

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0002"
down_revision: str | None = "0001"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

PURCHASE_STATUS = sa.Enum(
    "initial", "confirmed", "completed", name="credits_purchase_status"
)
TX_STATUS = sa.Enum(
    "locked", "confirmed", "canceled", "expired", name="credits_transaction_status"
)


def upgrade() -> None:
    PURCHASE_STATUS.create(op.get_bind())
    TX_STATUS.create(op.get_bind())

    op.create_table(
        "credits_purchases",
        sa.Column("credits_amount", sa.BigInteger(), nullable=False),
        sa.Column("package_name", sa.String(), nullable=False),
        sa.Column("metadata", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column(
            "status",
            postgresql.ENUM(
                "initial",
                "confirmed",
                "completed",
                name="credits_purchase_status",
                create_type=False,
            ),
            nullable=False,
        ),
        sa.Column("tg_user_id", sa.BigInteger(), nullable=True),
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("created_at", sa.TIMESTAMP(timezone=True), nullable=False),
        sa.Column("updated_at", sa.TIMESTAMP(timezone=True), nullable=True),
        sa.Column("deleted_at", sa.TIMESTAMP(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(
            ["tg_user_id"],
            ["tg_users.tg_id"],
            name=op.f("fk_credits_purchases__tg_user_id"),
            ondelete="SET NULL",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_credits_purchases")),
    )
    op.create_index(
        "ix_credits_purchases__hanging_purchases",
        "credits_purchases",
        ["status", "created_at"],
        unique=False,
    )
    op.create_index(
        op.f("ix_credits_purchases_tg_user_id"),
        "credits_purchases",
        ["tg_user_id"],
        unique=False,
    )

    op.create_table(
        "credits_transactions",
        sa.Column("amount", sa.BigInteger(), nullable=False),
        sa.Column(
            "status",
            postgresql.ENUM(
                "locked",
                "confirmed",
                "canceled",
                "expired",
                name="credits_transaction_status",
                create_type=False,
            ),
            nullable=False,
        ),
        sa.Column("tg_user_id", sa.BigInteger(), nullable=True),
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("created_at", sa.TIMESTAMP(timezone=True), nullable=False),
        sa.Column("updated_at", sa.TIMESTAMP(timezone=True), nullable=True),
        sa.Column("deleted_at", sa.TIMESTAMP(timezone=True), nullable=True),
        sa.CheckConstraint(
            "amount > 0",
            name=op.f("ck_credits_transactions__amount_positive"),
        ),
        sa.ForeignKeyConstraint(
            ["tg_user_id"],
            ["tg_users.tg_id"],
            name=op.f("fk_credits_transactions__tg_user_id"),
            ondelete="SET NULL",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_credits_transactions")),
    )
    op.create_index(
        "ix_credits_transactions__deleted_at",
        "credits_transactions",
        ["deleted_at"],
        unique=False,
    )
    op.create_index(
        "ix_credits_transactions__hanging_transactions",
        "credits_transactions",
        ["status", "created_at"],
        unique=False,
    )
    op.create_index(
        op.f("ix_credits_transactions_tg_user_id"),
        "credits_transactions",
        ["tg_user_id"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index(
        op.f("ix_credits_transactions_tg_user_id"), table_name="credits_transactions"
    )
    op.drop_index(
        "ix_credits_transactions__hanging_transactions",
        table_name="credits_transactions",
    )
    op.drop_index(
        "ix_credits_transactions__deleted_at", table_name="credits_transactions"
    )
    op.drop_table("credits_transactions")

    op.drop_index(
        op.f("ix_credits_purchases_tg_user_id"), table_name="credits_purchases"
    )
    op.drop_index(
        "ix_credits_purchases__hanging_purchases", table_name="credits_purchases"
    )
    op.drop_table("credits_purchases")

    TX_STATUS.drop(op.get_bind())
    PURCHASE_STATUS.drop(op.get_bind())
