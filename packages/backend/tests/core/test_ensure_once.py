import pytest
from redis.asyncio import Redis as AsyncRedis

from app.core.utils import ensure_once


async def test_ensure_once_runs_action(redis: AsyncRedis) -> None:
    executed = False

    async with ensure_once(redis, "test:action"):
        executed = True

    assert executed
    assert await redis.get("test:action") is not None


async def test_ensure_once_rejects_second_run(redis: AsyncRedis) -> None:
    async with ensure_once(redis, "test:action"):
        pass

    with pytest.raises(ValueError):
        async with ensure_once(redis, "test:action"):
            pass


async def test_ensure_once_allows_retry_after_error(redis: AsyncRedis) -> None:
    with pytest.raises(RuntimeError):
        async with ensure_once(redis, "test:action"):
            raise RuntimeError

    executed = False
    async with ensure_once(redis, "test:action"):
        executed = True

    assert executed
