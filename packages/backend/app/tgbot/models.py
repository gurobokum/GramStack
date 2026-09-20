from typing import Any

from sqlalchemy.dialects import postgresql
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import RecordModel, string_column


class Config(RecordModel):
    __tablename__ = "configs"

    name: Mapped[str] = string_column(64, unique=True)
    data: Mapped[dict[str, Any]] = mapped_column(
        postgresql.JSONB, nullable=False, default=dict
    )
