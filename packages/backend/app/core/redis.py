import enum


class RedisKey(enum.StrEnum):
    """
    Single place for the per-user redis keys the app stores.
    """

    PAGE = "page"

    def key(self, tg_user_id: int) -> str:
        return f"{self}:{tg_user_id}"
