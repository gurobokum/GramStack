import hashlib
import hmac
import json
import re
from datetime import timedelta
from typing import Annotated
from urllib.parse import unquote

from fastapi import Depends, HTTPException
from fastapi.security import APIKeyHeader
from starlette.status import HTTP_403_FORBIDDEN

from app.auth.models import TGUser
from app.auth.services import TGUserService
from app.conf import settings
from app.models.base import utc_now
from app.tgbot.schemas import UserTGData

INIT_DATA_TTL = timedelta(hours=6)


def validate_init_data(auth_key: str) -> dict[str, str]:
    """
    Check the telegram signature and the freshness of initData and return its
    fields. Every request carries initData, so it is validated on every call.
    """
    m = re.compile(r"^((.*?)&hash=(.*?))$").match(unquote(auth_key))
    if not m:
        raise HTTPException(
            status_code=HTTP_403_FORBIDDEN, detail="Invalid authentication credentials"
        )

    init_data = m.group(1)
    data_hash = m.group(3)
    data = {
        k: v for (k, v) in [p.split("=") for p in init_data.split("&")] if k != "hash"
    }
    data_check_string = "\n".join([f"{k}={data[k]}" for k in sorted(data.keys())])

    secret_key = hmac.new(
        b"WebAppData", settings.TGBOT_TOKEN.get_secret_value().encode(), hashlib.sha256
    ).digest()
    result_hash = hmac.new(
        secret_key, data_check_string.encode(), hashlib.sha256
    ).hexdigest()

    if not hmac.compare_digest(result_hash, data_hash):
        raise HTTPException(status_code=HTTP_403_FORBIDDEN, detail="Hash is not valid")

    auth_date = data.get("auth_date")
    if not auth_date or not auth_date.isdigit():
        raise HTTPException(
            status_code=HTTP_403_FORBIDDEN, detail="auth_date is required"
        )

    if utc_now().timestamp() > int(auth_date) + INIT_DATA_TTL.total_seconds():
        raise HTTPException(
            status_code=HTTP_403_FORBIDDEN,
            detail="auth_date is too old, please try again",
        )

    return data


async def get_user_or_create_with_tg_data(
    auth_key: Annotated[str, Depends(APIKeyHeader(name="x-telegram-auth"))],
    tg_user_svc: Annotated[TGUserService, Depends(TGUserService.inject)],
) -> TGUser:
    data = validate_init_data(auth_key)

    user_data = data.get("user")
    if not user_data:
        raise HTTPException(
            status_code=HTTP_403_FORBIDDEN, detail="Invalid authentication credentials"
        )

    user_tg_data = UserTGData.model_validate(json.loads(user_data))
    tg_user = await tg_user_svc.get_user_and_update(user_tg_data)
    if not tg_user:
        if settings.TGBOT_REQUIRES_INVITE:
            # TODO: needs to be improved
            # with custom error middleware
            raise HTTPException(
                status_code=HTTP_403_FORBIDDEN,
                detail="Signup without invite code is not allowed",
            )
        tg_user = await tg_user_svc.create(user_tg_data)
    return tg_user


AuthUser = Annotated[TGUser, Depends(get_user_or_create_with_tg_data)]
