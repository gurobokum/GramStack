import asyncio

import structlog
from redis.asyncio import Redis as AsyncRedis
from telegram import Bot, InlineKeyboardMarkup
from telegram.constants import ParseMode

from app.auth.services import TGUserService
from app.db import AsyncSessionMaker
from app.posthog import PostHogEvent, posthog
from app.tgbot.utils import send_or_mark_blocked

logger = structlog.get_logger()

BROADCAST_PREFIX = "broadcast"
BROADCAST_TTL = 7 * 24 * 3600


async def broadcast_all_users(
    bot: Bot,
    event_name: str,
    *,
    message: str,
    redis: AsyncRedis,
    session_maker: AsyncSessionMaker,
    parse_mode: ParseMode | None = None,
    photo: bytes | None = None,
    reply_markup: InlineKeyboardMarkup | None = None,
    limit: int = 50,
    total: int | float = float("+inf"),
    delay: float = 0.5,
    exclude_bot_blocked: bool = False,
) -> tuple[int, int]:
    """
    Send a message (or photo with caption) to every user, paginating through
    the user table. Safe to re-run: a redis key per event_name:tg_id skips
    users who already got it. Returns (success_count, fail_count).
    """
    structlog.contextvars.bind_contextvars(event_name=event_name)
    logger.info("Broadcast started")

    event_key = f"{BROADCAST_PREFIX}:{event_name}"
    should_exit = False
    last_tg_id: int | None = None

    async def count(outcome: str) -> None:
        await redis.incr(f"{event_key}:{outcome}")
        await redis.expire(f"{event_key}:{outcome}", BROADCAST_TTL)

    async with session_maker() as db_session:
        user_svc = TGUserService(db_session)

        while not should_exit:
            users = await user_svc.list_users(
                limit=limit,
                after_tg_id=last_tg_id,
                exclude_banned=True,
                exclude_bot_blocked=exclude_bot_blocked,
            )
            if not users:
                break
            last_tg_id = users[-1].tg_id

            for user in users:
                if total <= 0:
                    logger.info("Broadcast total limit reached")
                    should_exit = True
                    break

                was_sent = await redis.get(f"{event_key}:user:{user.tg_id}")
                if was_sent:
                    logger.info(
                        "Broadcast is already sent to the user", tg_user_id=user.tg_id
                    )
                    continue

                if photo is not None:
                    send = bot.send_photo(
                        chat_id=user.tg_id,
                        photo=photo,
                        caption=message,
                        parse_mode=parse_mode,
                        reply_markup=reply_markup,
                    )
                else:
                    send = bot.send_message(
                        chat_id=user.tg_id,
                        text=message,
                        parse_mode=parse_mode,
                        reply_markup=reply_markup,
                    )

                try:
                    sent = await send_or_mark_blocked(user_svc, user.tg_id, send)
                except Exception as e:
                    logger.error(
                        "Failed to send the broadcast to the user",
                        tg_user_id=user.tg_id,
                        error=str(e),
                    )
                    await count("fail")
                else:
                    if sent:
                        await redis.set(
                            f"{event_key}:user:{user.tg_id}",
                            "1",
                            ex=BROADCAST_TTL,
                        )
                        if user.is_bot_blocked and await user_svc.mark_bot_unblocked(
                            user.tg_id
                        ):
                            posthog.capture(user.tg_id, PostHogEvent.USER_UNBLOCKED_BOT)
                        total -= 1
                        await count("success")
                        logger.info("Broadcast sent to the user", tg_user_id=user.tg_id)
                    else:
                        await count("fail")
                await asyncio.sleep(delay)

    success_count = int(await redis.get(f"{event_key}:success") or 0)
    fail_count = int(await redis.get(f"{event_key}:fail") or 0)
    logger.info(
        "Broadcast completed", success_count=success_count, fail_count=fail_count
    )
    return success_count, fail_count
