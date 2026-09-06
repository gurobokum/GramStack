import json
from typing import Annotated

import structlog
from fastapi import APIRouter, Depends, HTTPException
from telegram import Bot, LabeledPrice

from app.conf import settings
from app.core.http_errors import HTTPUnauthorizedError
from app.credits.schemas import BuyCreditsRequest, CreditsPackage
from app.credits.services import CreditsPurchaseService
from app.dependencies import AuthUser
from app.openapi import generate_unique_id_function

logger = structlog.get_logger()

router = APIRouter(
    prefix="/credits",
    tags=["tg_credits"],
    generate_unique_id_function=generate_unique_id_function("tg::credits"),
    responses={401: {"model": HTTPUnauthorizedError}},
)

"""
1 tg star costs ~0.2 $
"""
packages = [
    CreditsPackage(package_name="starter", credits_amount=10, stars_amount=100),
    CreditsPackage(package_name="business", credits_amount=30, stars_amount=300),
    CreditsPackage(package_name="enterprise", credits_amount=100, stars_amount=1000),
]


@router.get(
    "/packages",
    description="Get list of available packages",
)
async def list_packages(
    user: AuthUser,
) -> list[CreditsPackage]:
    return packages


@router.put(
    "/send_invoice",
    description="Send payment invoice for user",
)
async def send_invoice(
    user: AuthUser,
    data: BuyCreditsRequest,
    credits_svc: Annotated[
        CreditsPurchaseService, Depends(CreditsPurchaseService.inject)
    ],
) -> None:
    try:
        package = [
            package for package in packages if package.package_name == data.package_name
        ][0]
    except IndexError:
        logger.exception(
            f"Invalid package name {data.package_name}", tg_user_id=user.tg_id
        )
        raise HTTPException(status_code=400, detail="Invalid package name") from None

    purchase = await credits_svc.init_credits_purchase(user.tg_id, package)

    await Bot(settings.TGBOT_TOKEN.get_secret_value()).send_invoice(
        chat_id=user.tg_id,
        title="GramStack",
        description=f"Buy {package.credits_amount} credits for GramStack",
        payload=json.dumps({"code": "buy_credits", "id": str(purchase.id)}),
        provider_token="",
        currency="XTR",
        prices=[LabeledPrice(label="Stars", amount=package.stars_amount)],
    )
