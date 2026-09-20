import io

import boto3
import pytest
from botocore.exceptions import ClientError
from botocore.response import StreamingBody
from botocore.stub import Stubber
from pydantic import HttpUrl
from types_boto3_s3 import S3Client

from app.conf import settings
from app.core.errors import AppError
from app.core.s3 import (
    download_from_s3,
    file_exists_in_s3,
    get_full_url,
    get_public_url,
    get_signed_url,
    remove_from_s3,
    save_to_s3,
)


def make_stubbed_client() -> tuple[S3Client, Stubber]:
    client = boto3.client(
        "s3",
        region_name="us-east-1",
        aws_access_key_id="test",
        aws_secret_access_key="test",
    )
    return client, Stubber(client)


async def test_download_from_s3() -> None:
    client, stubber = make_stubbed_client()
    content = b"file-content"
    stubber.add_response(
        "get_object",
        {"Body": StreamingBody(io.BytesIO(content), len(content))},
        {"Bucket": settings.STORAGE_BUCKET, "Key": "a/b.bin"},
    )
    with stubber:
        assert await download_from_s3(client, "a/b.bin") == content


async def test_save_to_s3() -> None:
    client, stubber = make_stubbed_client()
    stubber.add_response("put_object", {})
    with stubber:
        await save_to_s3(client, io.BytesIO(b"data"), "a/b.bin")
    stubber.assert_no_pending_responses()


async def test_remove_from_s3() -> None:
    client, stubber = make_stubbed_client()
    stubber.add_response(
        "delete_object", {}, {"Bucket": settings.STORAGE_BUCKET, "Key": "a/b.bin"}
    )
    with stubber:
        await remove_from_s3(client, "a/b.bin")
    stubber.assert_no_pending_responses()


async def test_remove_from_s3_with_bucket() -> None:
    client, stubber = make_stubbed_client()
    stubber.add_response(
        "delete_object", {}, {"Bucket": "public-bucket", "Key": "a/b.bin"}
    )
    with stubber:
        await remove_from_s3(client, "a/b.bin", bucket="public-bucket")
    stubber.assert_no_pending_responses()


async def test_file_exists_in_s3_true() -> None:
    client, stubber = make_stubbed_client()
    stubber.add_response(
        "head_object", {}, {"Bucket": settings.STORAGE_BUCKET, "Key": "a/b.bin"}
    )
    with stubber:
        assert await file_exists_in_s3(client, "a/b.bin") is True


async def test_file_exists_in_s3_false_on_404() -> None:
    client, stubber = make_stubbed_client()
    stubber.add_client_error(
        "head_object", service_error_code="404", http_status_code=404
    )
    with stubber:
        assert await file_exists_in_s3(client, "a/b.bin") is False


async def test_file_exists_in_s3_raises_on_other_errors() -> None:
    client, stubber = make_stubbed_client()
    stubber.add_client_error(
        "head_object", service_error_code="403", http_status_code=403
    )
    with stubber, pytest.raises(ClientError):
        await file_exists_in_s3(client, "a/b.bin")


def test_get_signed_url() -> None:
    client, _ = make_stubbed_client()
    url = get_signed_url(client, "a/b.bin", expires_in=60)
    assert settings.STORAGE_BUCKET in url
    assert "a/b.bin" in url


def test_get_full_url() -> None:
    expected = "https://storage.test.example.com/test-bucket/a/b.jpg"
    assert get_full_url("a/b.jpg") == expected
    assert get_full_url("/a/b.jpg") == expected


def test_get_public_url(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        settings, "PUBLIC_STORAGE_URL", HttpUrl("https://public.test.example.com")
    )
    expected = "https://public.test.example.com/a/b.jpg"
    assert get_public_url("a/b.jpg") == expected
    assert get_public_url("/a/b.jpg") == expected


def test_get_public_url_requires_setting(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(settings, "PUBLIC_STORAGE_URL", None)
    with pytest.raises(AppError):
        get_public_url("a/b.jpg")
