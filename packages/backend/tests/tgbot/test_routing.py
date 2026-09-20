from redis.asyncio import Redis as AsyncRedis
from telegram import Update

from app.auth.services import TGUserService
from app.core.redis import RedisKey
from app.db import AsyncSessionMaker
from app.tgbot.context import Context
from app.tgbot.routing import PAGE_TTL, Route, admin_gate, router, track_page
from app.tgbot.schemas import UserTGData
from tests.helpers.bot import make_offline_bot
from tests.helpers.updates import make_context, make_update


async def test_track_page_saves_returned_page(
    redis: AsyncRedis, db_session_maker: AsyncSessionMaker
) -> None:
    bot = await make_offline_bot()
    Context.redis = redis
    context = make_context(bot, db_session_maker)

    async def handler(update: Update, context: Context) -> str | None:
        return "flow:step_one"

    result = await track_page(handler)(make_update(bot, user_id=5001), context)

    assert result is None
    assert await redis.get(RedisKey.PAGE.key(5001)) == b"flow:step_one"
    assert 0 < await redis.ttl(RedisKey.PAGE.key(5001)) <= PAGE_TTL


async def test_track_page_loads_and_consumes_page(
    redis: AsyncRedis, db_session_maker: AsyncSessionMaker
) -> None:
    bot = await make_offline_bot()
    Context.redis = redis
    context = make_context(bot, db_session_maker)
    await redis.set(RedisKey.PAGE.key(5002), "flow:step_one")

    seen: list[str | None] = []

    async def handler(update: Update, context: Context) -> str | None:
        seen.append(context.page)
        return None

    await track_page(handler)(make_update(bot, user_id=5002), context)

    assert seen == ["flow:step_one"]
    assert await redis.get(RedisKey.PAGE.key(5002)) is None


async def test_router_dispatches_by_page(
    db_session_maker: AsyncSessionMaker,
) -> None:
    bot = await make_offline_bot()
    context = make_context(bot, db_session_maker)
    calls: list[str] = []

    async def step_one(update: Update, context: Context) -> str | None:
        calls.append("step_one")
        return None

    async def step_with_id(update: Update, context: Context) -> str | None:
        assert context.page is not None
        calls.append(context.page.rsplit(":", 1)[1])
        return None

    handle = router(
        [
            Route(r"^flow:step_one$", step_one),
            Route(r"^flow:item:\d+$", step_with_id),
        ]
    )
    update = make_update(bot, text="some input", user_id=5003)

    context.page = None
    await handle(update, context)
    assert calls == []

    context.page = "flow:step_one"
    await handle(update, context)
    assert calls == ["step_one"]

    context.page = "flow:item:42"
    await handle(update, context)
    assert calls == ["step_one", "42"]

    context.page = "flow:unknown"
    await handle(update, context)
    assert calls == ["step_one", "42"]


async def test_admin_gate_blocks_non_admin(
    db_session_maker: AsyncSessionMaker,
) -> None:
    async with db_session_maker() as session:
        await TGUserService(session).create(
            UserTGData.model_validate({"id": 6001, "username": "testuser6001"})
        )

    bot = await make_offline_bot()
    context = make_context(bot, db_session_maker)
    calls: list[int] = []

    async def handler(update: Update, context: Context) -> str | None:
        calls.append(1)
        return "admin:page"

    wrapped = admin_gate(handler)

    result = await wrapped(make_update(bot, user_id=6001), context)
    assert result is None
    assert calls == []

    result = await wrapped(make_update(bot, user_id=999999), context)
    assert result is None
    assert calls == []


async def test_admin_gate_allows_admin(db_session_maker: AsyncSessionMaker) -> None:
    async with db_session_maker() as session:
        svc = TGUserService(session)
        await svc.create(
            UserTGData.model_validate({"id": 6002, "username": "testuser6002"})
        )
        await svc.update_user(6002, is_admin=True)

    bot = await make_offline_bot()
    context = make_context(bot, db_session_maker)
    calls: list[int] = []

    async def handler(update: Update, context: Context) -> str | None:
        calls.append(1)
        return "admin:page"

    wrapped = admin_gate(handler)

    result = await wrapped(make_update(bot, user_id=6002), context)
    assert result == "admin:page"
    assert calls == [1]


def test_route_overlaps() -> None:
    async def handler(update: Update, context: Context) -> str | None:
        return None

    creds = Route(r"^admin:acc:add$", handler)
    link = Route(r"^admin:conn:add:", handler)

    assert not creds.overlaps(link)
    assert not creds.overlaps(Route(r"^admin:acc:add_more$", handler))
    assert creds.overlaps(Route(r"^admin:acc:add$", handler))
    assert creds.overlaps(Route(r"^admin:acc:", handler))
    assert link.overlaps(Route(r"^admin:conn:add:extra$", handler))
    assert link.overlaps(Route(r"^admin:", handler))
