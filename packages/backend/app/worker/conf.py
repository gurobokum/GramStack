import contextlib
import functools
from collections.abc import AsyncGenerator, Callable
from datetime import datetime
from typing import Any, Protocol, TypedDict

import structlog
from arq.connections import RedisSettings
from arq.cron import CronJob, cron
from arq.worker import Function, func
from pydantic import BaseModel, ConfigDict
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession

from app.conf import settings
from app.db import AsyncSessionMaker, create_async_engine, create_session_maker

logger = structlog.get_logger()


class WorkerContext(TypedDict):
    engine: AsyncEngine
    db_session_maker: AsyncSessionMaker


class JobContext(BaseModel):
    model_config = ConfigDict(arbitrary_types_allowed=True)
    job_id: str
    job_try: int
    enqueue_time: datetime
    score: int

    engine: AsyncEngine
    db_session_maker: AsyncSessionMaker
    db_session: AsyncSession

    @contextlib.asynccontextmanager
    async def get_db_session(self) -> AsyncGenerator[AsyncSession]:
        async with self.db_session_maker() as db_session:
            try:
                yield db_session
            finally:
                await db_session.aclose()


class WorkerSettings:
    functions: list[Function] = []
    cron_jobs: list[CronJob] = []
    queue_name: str = "gramstack:queue"
    job_timeout = 60 * 60

    redis_settings = RedisSettings.from_dsn(settings.REDIS_URL.get_secret_value())

    @staticmethod
    async def on_startup(ctx: WorkerContext) -> None:
        logger.info(
            "Worker startup",
            tasks=sorted(f.name for f in WorkerSettings.functions),
            crons=sorted(c.name for c in WorkerSettings.cron_jobs if c.name),
        )
        engine = ctx["engine"] = create_async_engine(settings.DATABASE_URL, "worker")
        ctx["db_session_maker"] = create_session_maker(engine)

    @staticmethod
    async def on_shutdown(ctx: WorkerContext) -> None:
        await ctx["engine"].dispose()
        logger.info("Worker shutdown")


class Task[**P](Protocol):
    async def __call__(
        self, ctx: JobContext, *args: P.args, **kwargs: P.kwargs
    ) -> Any: ...


def task[**P](
    name: str,
) -> Callable[[Task[P]], Task[P]]:
    def decorator(
        f: Task[P],
    ) -> Task[P]:
        WorkerSettings.functions.append(func(_with_job_context(f), name=name))
        return f

    return decorator


def cron_task[**P](
    name: str,
    **cron_kwargs: Any,
) -> Callable[[Task[P]], Task[P]]:
    """
    Register a task arq runs on a schedule, e.g. cron_task("name", minute={0, 30}).
    """

    def decorator(
        f: Task[P],
    ) -> Task[P]:
        WorkerSettings.cron_jobs.append(
            cron(_with_job_context(f), name=name, **cron_kwargs)
        )
        return f

    return decorator


def _with_job_context[**P](f: Task[P]) -> Callable[..., Any]:
    @functools.wraps(f)
    async def _func(ctx: dict[Any, Any], *args: P.args, **kwargs: P.kwargs) -> Any:
        db_session_maker = ctx["db_session_maker"]
        if not db_session_maker:
            raise ValueError("Database session maker is None")

        async with db_session_maker() as db_session:
            job_context = JobContext.model_validate({**ctx, "db_session": db_session})
            return await f(job_context, *args, **kwargs)

    return _func
