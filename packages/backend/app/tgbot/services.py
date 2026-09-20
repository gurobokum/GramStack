from typing import TypeVar

from sqlalchemy import sql
from sqlalchemy.dialects.postgresql import insert as pg_insert

from app.core.services import BaseService
from app.models.base import utc_now
from app.tgbot.models import Config
from app.tgbot.schemas import BaseConfig

C = TypeVar("C", bound=BaseConfig)


class ConfigService(BaseService):
    async def get_config(self, schema: type[C]) -> C:
        """
        Returns the stored payload validated by the schema, or a
        default-constructed schema when the row does not exist.
        """
        async with self.tx():
            result = await self.db_session.execute(
                sql.select(Config).filter_by(name=schema.config_name)
            )
        config = result.scalar_one_or_none()
        return schema.model_validate(config.data) if config else schema()

    async def set_config(self, payload: BaseConfig) -> Config:
        data = payload.model_dump(mode="json")
        async with self.tx():
            result = await self.db_session.execute(
                pg_insert(Config)
                .values(name=type(payload).config_name, data=data)
                .on_conflict_do_update(
                    index_elements=["name"],
                    set_={"data": data, "updated_at": utc_now()},
                )
                .returning(Config)
            )
        return result.scalar_one()
