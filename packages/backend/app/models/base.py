import base64
from datetime import UTC, datetime
from typing import Any, TypeVar, cast
from uuid import UUID

import sqlalchemy
from fastapi.encoders import jsonable_encoder
from pydantic import BaseModel as PydanticBaseModel
from pydantic import EmailStr, HttpUrl, TypeAdapter
from sqlalchemy import ColumnElement, LargeBinary, MetaData, String, TypeDecorator, func
from sqlalchemy.dialects import postgresql
from sqlalchemy.engine import Dialect
from sqlalchemy.ext.asyncio import AsyncAttrs
from sqlalchemy.orm import DeclarativeBase, Mapped, MappedColumn, mapped_column
from sqlalchemy.sql.operators import OperatorType
from sqlalchemy.types import TIMESTAMP
from uuid_utils.compat import uuid7

from app.conf import settings
from app.core import crypto


def utc_now() -> datetime:
    return datetime.now(UTC)


"""
https://docs.sqlalchemy.org/en/20/core/constraints.html#configuring-a-naming-convention-for-a-metadata-collection

pkey for a Primary Key constraint
key for a Unique constraint
excl for an Exclusion constraint
idx for any other kind of index
fkey for a Foreign key
check for a Check constraint
seq for all sequences
"""
metadata = MetaData(
    naming_convention={
        "ix": "ix_%(column_0_N_label)s",
        "uq": "uq_%(table_name)s__%(column_0_N_name)s",
        "ck": "ck_%(table_name)s__%(constraint_name)s",
        "fk": "fk_%(table_name)s_%(referred_table_name)s__%(column_0_N_name)s",
        "pk": "pk_%(table_name)s",
    }
)

# See https://github.com/dropbox/sqlalchemy-stubs/issues/94
PostgresUUID = cast(
    sqlalchemy.types.TypeEngine[UUID],
    postgresql.UUID(as_uuid=True),
)


class ValueEnum(sqlalchemy.Enum):
    """
    Enum column type that stores members' `.value` in Postgres instead of the
    default `.name`.
    """

    def __init__(self, *enums: Any, **kwargs: Any) -> None:
        kwargs.setdefault("values_callable", lambda e: [i.value for i in e])
        super().__init__(*enums, **kwargs)


class HashType(TypeDecorator[str]):
    impl = LargeBinary(64)
    cache_ok = True

    def process_result_value(self, value: bytes | None, dialect: Dialect) -> str | None:
        if value is None:
            return None
        return base64.urlsafe_b64encode(value).decode("utf-8")


class EmailType(TypeDecorator[str]):
    """
    Stores emails lowercased and compares them case-insensitively.

    Replacement for sqlalchemy_utils.types.EmailType.
    """

    impl = String(255)
    cache_ok = True

    class Comparator(String.Comparator[str]):
        def operate(
            self, op: OperatorType, *other: Any, **kwargs: Any
        ) -> ColumnElement[Any]:
            lowered = [func.lower(o) for o in other]
            return cast(
                ColumnElement[Any], op(func.lower(self.expr), *lowered, **kwargs)
            )

    comparator_factory = Comparator

    def process_bind_param(self, value: str | None, dialect: Dialect) -> str | None:
        if value is None:
            return None
        return value.lower()


class EncryptedString(TypeDecorator[str]):
    """
    Stores the value AES-256-GCM-encrypted with SECRET_KEY (see app/core/crypto.py).
    """

    impl = LargeBinary
    cache_ok = True

    def process_bind_param(self, value: str | None, dialect: Dialect) -> bytes | None:
        if value is None:
            return None
        return crypto.encrypt(
            value,
            settings.SECRET_KEY.get_secret_value(),
            settings.SECRET_KEY_VERSION,
        )

    def process_result_value(self, value: bytes | None, dialect: Dialect) -> str | None:
        if value is None:
            return None
        return crypto.decrypt(value, settings.SECRET_KEY.get_secret_value())


def string_column(
    length: int | None = None,
    nullable: bool = False,
    default: str | None = "",
    **kwargs: Any,
) -> Any:
    """
    Factory for creating string columns with sane defaults.

    This follows the convention of avoiding NULL for string columns.
    Instead, an empty string is used as the default value when the column is not nullable.
    """
    return mapped_column(String(length), nullable=nullable, default=default, **kwargs)


class BaseModel(AsyncAttrs, DeclarativeBase):
    __abstract__ = True
    type_annotation_map = {
        datetime: TIMESTAMP(timezone=True),
        HttpUrl: String(4096),
        EmailStr: EmailType(),
        UUID: PostgresUUID,
    }

    metadata = metadata


class TimestampModel(BaseModel):
    __abstract__ = True

    created_at: Mapped[datetime] = mapped_column(default=utc_now)
    updated_at: Mapped[datetime | None] = mapped_column(onupdate=utc_now, default=None)
    deleted_at: Mapped[datetime | None] = mapped_column(default=None)


class RecordModel(TimestampModel):
    __abstract__ = True

    id: MappedColumn[UUID] = mapped_column(
        PostgresUUID, primary_key=True, default=uuid7
    )

    def __str__(self) -> str:
        return f"{self.__class__.__qualname__}(id='{self.id}')"

    def __repr__(self) -> str:
        return (
            f"{self.__class__.__module__}.{self.__class__.__qualname__}(id='{self.id}')"
        )


T = TypeVar("T")


class PydanticJSON(TypeDecorator[T]):
    """
    Creates a JSONB column that stores Pydantic models.
    https://gist.github.com/imankulov/4051b7805ad737ace7d8de3d3f934d6b
    """

    impl = postgresql.JSONB
    cache_ok = True

    def __init__(
        self, pydantic_model: T, none_as_null: bool = False, *args: Any, **kwargs: Any
    ) -> None:
        super().__init__(*args, **kwargs)
        self.pydantic_model = pydantic_model
        self.type_adapter: TypeAdapter[T] = TypeAdapter(pydantic_model)
        self.none_as_null = none_as_null

    def process_bind_param(self, value: T | None, dialect: Dialect) -> Any:
        if value is None and self.none_as_null:
            return None
        return jsonable_encoder(value)

    def process_result_value(self, value: str | None, dialect: Dialect) -> T | None:
        if value is None:
            return None
        return self.type_adapter.validate_python(value)


class ErrorSchema(PydanticBaseModel):
    message: str
    code: str | None = None
