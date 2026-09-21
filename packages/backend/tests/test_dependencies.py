import hashlib
import hmac
import json
from datetime import timedelta
from typing import Any

import pytest
from fastapi import HTTPException

from app.auth.services import TGUserService
from app.conf import settings
from app.db import AsyncSessionMaker
from app.dependencies import get_user_or_create_with_tg_data, validate_init_data
from app.models.base import utc_now

TG_USER_ID = 300


def make_init_data(
    user: dict[str, Any] | None = None,
    *,
    auth_date: int | None = None,
    token: str | None = None,
) -> str:
    fields: dict[str, str] = {}
    if user is not None:
        fields["user"] = json.dumps(user, separators=(",", ":"))
    if auth_date is not None:
        fields["auth_date"] = str(auth_date)

    data_check_string = "\n".join(f"{k}={fields[k]}" for k in sorted(fields))
    secret_key = hmac.new(
        b"WebAppData",
        (token or settings.TGBOT_TOKEN.get_secret_value()).encode(),
        hashlib.sha256,
    ).digest()
    data_hash = hmac.new(
        secret_key, data_check_string.encode(), hashlib.sha256
    ).hexdigest()

    query = "&".join(f"{k}={v}" for k, v in fields.items())
    return f"{query}&hash={data_hash}"


def valid_init_data(tg_id: int = TG_USER_ID) -> str:
    return make_init_data(
        {"id": tg_id, "username": "tester"}, auth_date=int(utc_now().timestamp())
    )


def test_valid_init_data_returns_fields() -> None:
    data = validate_init_data(valid_init_data())

    assert json.loads(data["user"])["id"] == TG_USER_ID
    assert "hash" not in data


def test_tampered_user_is_rejected() -> None:
    init_data = valid_init_data()
    forged = init_data.replace('"id":300', '"id":999')

    with pytest.raises(HTTPException) as e:
        validate_init_data(forged)

    assert e.value.status_code == 403


def test_wrong_token_is_rejected() -> None:
    init_data = make_init_data(
        {"id": TG_USER_ID}, auth_date=int(utc_now().timestamp()), token="99999:other"
    )

    with pytest.raises(HTTPException) as e:
        validate_init_data(init_data)

    assert e.value.status_code == 403


def test_missing_hash_is_rejected() -> None:
    with pytest.raises(HTTPException) as e:
        validate_init_data("user={}&auth_date=1")

    assert e.value.status_code == 403


def test_missing_auth_date_is_rejected() -> None:
    with pytest.raises(HTTPException) as e:
        validate_init_data(make_init_data({"id": TG_USER_ID}))

    assert e.value.status_code == 403


def test_stale_auth_date_is_rejected() -> None:
    stale = int((utc_now() - timedelta(hours=7)).timestamp())

    with pytest.raises(HTTPException) as e:
        validate_init_data(make_init_data({"id": TG_USER_ID}, auth_date=stale))

    assert e.value.status_code == 403


async def test_forged_init_data_does_not_authenticate(
    db_session_maker: AsyncSessionMaker,
) -> None:
    forged = f"user={json.dumps({'id': TG_USER_ID})}&auth_date=1&hash=deadbeef"

    async with db_session_maker() as session:
        with pytest.raises(HTTPException) as e:
            await get_user_or_create_with_tg_data(forged, TGUserService(session))

    assert e.value.status_code == 403


async def test_valid_init_data_creates_user(
    db_session_maker: AsyncSessionMaker,
) -> None:
    async with db_session_maker() as session:
        user = await get_user_or_create_with_tg_data(
            valid_init_data(), TGUserService(session)
        )

    assert user.tg_id == TG_USER_ID
    assert user.username == "tester"
