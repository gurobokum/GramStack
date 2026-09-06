from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager
from functools import lru_cache
from typing import TypeVar

from pydantic import BaseModel, TypeAdapter
from redis.asyncio import Redis as AsyncRedis
from ruamel.yaml import YAML

YamlType = TypeVar("YamlType", bound=BaseModel)


@asynccontextmanager
async def ensure_once(redis: AsyncRedis, key: str) -> AsyncGenerator[None]:
    """
    Ensure action is executed only once using Redis key.
    Raises error if already executed.
    """
    if await redis.get(key):
        raise ValueError(f"Action already executed for key: '{key}'")

    yield

    await redis.set(key, "1")


@lru_cache
def load_yaml(
    path: str, model_type: type[YamlType], *, key: str | None = None
) -> YamlType:
    type_adapter = TypeAdapter(model_type)
    with open(path) as fd:
        data = YAML().load(fd)
        return type_adapter.validate_python(data[key] if key else data)
