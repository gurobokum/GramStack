import json
from uuid import UUID

from dishka import FromDishka
from telegram import Update
from telegram.ext import MessageHandler, PreCheckoutQueryHandler, filters

from app.auth.models import TGUser
from app.core.errors import AppError, NotFoundError
from app.credits.i18n import HandlersTexts as CreditsHandlersTexts
from app.credits.models import CreditsPurchaseStatus
from app.credits.services import CreditsPurchaseService
from app.posthog import PostHogEvent, posthog
from app.tgbot.context import Context
from app.tgbot.dishka import inject
from app.tgbot.routing import Handlers


@inject
async def pre_checkout(
    update: Update,
    context: Context,
    user: FromDishka[TGUser],
    credits_svc: FromDishka[CreditsPurchaseService],
) -> None:
    query = update.pre_checkout_query
    if not query:
        raise AppError("No pre_checkout_query in update")
    payload = json.loads(query.invoice_payload)

    if payload["code"] != "buy_credits":
        raise AppError(
            f"Invalid payload code: '{payload['code']}'", tg_user_id=user.tg_id
        )
    purchase = await credits_svc.get_purchase(UUID(payload["id"]))
    if not purchase:
        raise NotFoundError("Purchase not found")

    if purchase.tg_user_id != user.tg_id:
        raise AppError("User id mismatch")

    if purchase.status == CreditsPurchaseStatus.COMPLETED:
        await query.answer(
            ok=False,
            error_message="Purchase already completed",
        )

    await credits_svc.confirm_purchase(purchase.id)
    await query.answer(ok=True)


@inject
async def complete_payment(
    update: Update,
    context: Context,
    user: FromDishka[TGUser],
    credits_svc: FromDishka[CreditsPurchaseService],
    texts: FromDishka[CreditsHandlersTexts],
) -> None:
    message = update.message
    if not message:
        raise AppError("No message in update")

    successful_payment = message.successful_payment
    if not successful_payment:
        raise AppError("No successful_payment in message")

    payload = json.loads(successful_payment.invoice_payload)

    if payload["code"] != "buy_credits":
        raise AppError(
            f"Invalid payload code: '{payload['code']}'", tg_user_id=user.tg_id
        )

    purchase = await credits_svc.get_purchase(UUID(payload["id"]))
    if not purchase or purchase.status != CreditsPurchaseStatus.CONFIRMED:
        await message.reply_text(texts.complete_payment.purchase_failed)
        raise NotFoundError("[CRITICAL] Purchase not found")

    await credits_svc.complete_purchase(
        purchase.id,
        successful_payment.provider_payment_charge_id,
        successful_payment.telegram_payment_charge_id,
    )
    posthog.capture(
        user.tg_id,
        PostHogEvent.PURCHASED_CREDITS,
        {
            "credits_amount": purchase.credits_amount,
            "package_name": purchase.package_name,
        },
    )


handlers = Handlers(
    payments=[
        PreCheckoutQueryHandler(pre_checkout),
        MessageHandler(filters.SUCCESSFUL_PAYMENT, complete_payment),
    ]
)
