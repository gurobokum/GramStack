"""auth

Revision ID: 0001
Revises:
Create Date: 2026-09-20 17:40:00.000000

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0001"
down_revision: str | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

# tg_users and tg_invite_codes reference each other, so this constraint is added
# after both tables exist
INVITE_CODE_FK = "fk_tg_users_tg_invite_codes__redeemed_invite_code"


def upgrade() -> None:
    op.create_table(
        "tg_users",
        sa.Column("tg_id", sa.BigInteger(), nullable=False),
        sa.Column("username", sa.String(length=64), nullable=False),
        sa.Column("first_name", sa.String(length=64), nullable=False),
        sa.Column("last_name", sa.String(length=64), nullable=False),
        sa.Column("phone", sa.String(length=64), nullable=False),
        sa.Column("language_code", sa.String(length=8), nullable=False),
        sa.Column("language", sa.String(length=8), nullable=False),
        sa.Column("is_bot", sa.Boolean(), nullable=False),
        sa.Column("is_banned", sa.Boolean(), nullable=False),
        sa.Column("is_bot_blocked", sa.Boolean(), nullable=False),
        sa.Column("is_admin", sa.Boolean(), nullable=False),
        sa.Column("credits_balance", sa.Integer(), server_default="0", nullable=False),
        sa.Column("redeemed_invite_code", sa.String(), nullable=True),
        sa.Column("inviter_id", sa.BigInteger(), nullable=True),
        sa.Column("created_at", sa.TIMESTAMP(timezone=True), nullable=False),
        sa.Column("updated_at", sa.TIMESTAMP(timezone=True), nullable=True),
        sa.Column("deleted_at", sa.TIMESTAMP(timezone=True), nullable=True),
        sa.CheckConstraint(
            "credits_balance >= 0",
            name=op.f("ck_tg_users__tg_users__credits_balance_positive"),
        ),
        sa.ForeignKeyConstraint(
            ["inviter_id"],
            ["tg_users.tg_id"],
            name=op.f("fk_tg_users_tg_users__inviter_id"),
            ondelete="SET NULL",
        ),
        sa.PrimaryKeyConstraint("tg_id", name=op.f("pk_tg_users")),
    )
    op.create_index(op.f("ix_tg_users_inviter_id"), "tg_users", ["inviter_id"])
    op.create_table(
        "tg_invite_codes",
        sa.Column("code", sa.String(), nullable=False),
        sa.Column("uses_left", sa.Integer(), nullable=False),
        sa.Column("is_created_by_admin", sa.Boolean(), nullable=False),
        sa.Column("tg_user_id", sa.BigInteger(), nullable=True),
        sa.Column("created_at", sa.TIMESTAMP(timezone=True), nullable=False),
        sa.Column("updated_at", sa.TIMESTAMP(timezone=True), nullable=True),
        sa.Column("deleted_at", sa.TIMESTAMP(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(
            ["tg_user_id"],
            ["tg_users.tg_id"],
            name=op.f("fk_tg_invite_codes_tg_users__tg_user_id"),
        ),
        sa.PrimaryKeyConstraint("code", name=op.f("pk_tg_invite_codes")),
    )
    op.create_index(
        op.f("ix_tg_invite_codes_tg_user_id"),
        "tg_invite_codes",
        ["tg_user_id"],
        unique=False,
    )
    op.create_foreign_key(
        INVITE_CODE_FK,
        "tg_users",
        "tg_invite_codes",
        ["redeemed_invite_code"],
        ["code"],
    )


def downgrade() -> None:
    op.drop_constraint(INVITE_CODE_FK, "tg_users", type_="foreignkey")
    op.drop_index(op.f("ix_tg_invite_codes_tg_user_id"), table_name="tg_invite_codes")
    op.drop_table("tg_invite_codes")
    op.drop_index(op.f("ix_tg_users_inviter_id"), table_name="tg_users")
    op.drop_table("tg_users")
