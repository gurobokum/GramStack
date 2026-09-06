from datetime import timedelta

import structlog

from app.credits.services import CreditsService
from app.worker.conf import JobContext, cron_task

logger = structlog.get_logger()

# Must stay well above the worst-case legitimate job duration, or a slow job
# gets mistaken for dead.
CREDITS_LOCK_TTL = timedelta(minutes=30)


@cron_task("expire_locked_credits", hour={4}, minute={0})
async def expire_locked_credits(ctx: JobContext) -> None:
    expired = await CreditsService(ctx.db_session).expire_locked_credits(
        CREDITS_LOCK_TTL
    )
    if expired.count:
        # Anything reclaimed means a worker died mid-job - a health signal,
        # not routine.
        logger.warning(
            "Expired stale credit locks", count=expired.count, refunded=expired.total
        )
