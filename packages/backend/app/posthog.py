import enum
from typing import Any

import structlog
from posthog import Posthog  # type: ignore[attr-defined]

from app.conf import settings

logger = structlog.get_logger()


class PostHogEvent(str, enum.Enum):
    SIGNED_UP = "user_signed_up"
    STARTED = "user_started"
    PURCHASED_CREDITS = "user_purchased_credits"
    NO_CREDITS = "user_no_credits"
    USER_BLOCKED_BOT = "user_blocked_bot"
    USER_UNBLOCKED_BOT = "user_unblocked_bot"

    def __str__(self) -> str:
        return self.value


class AppPosthog(Posthog):  # type: ignore[misc]
    def capture(
        self,
        distinct_id: str | int,
        event: str,
        properties: dict[str, Any] | None = None,
        **kwargs: Any,
    ) -> None:
        props = {"tgbot_name": settings.TGBOT_NAME, **(properties or {})}
        super().capture(
            distinct_id=distinct_id, event=event, properties=props, **kwargs
        )


posthog = AppPosthog(
    settings.POSTHOG_API_KEY.get_secret_value() if settings.POSTHOG_API_KEY else "",
    host=settings.POSTHOG_HOST or "",
)

if not settings.POSTHOG_API_KEY or not settings.POSTHOG_HOST:
    logger.info("PostHog is not configured, tracking disabled")
    posthog.disabled = True
