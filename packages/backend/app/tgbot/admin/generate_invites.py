import structlog
from dishka import FromDishka
from telegram import Chat, Update
from telegram.constants import ParseMode

from app.auth.models import TGAdminUser
from app.auth.services import TGInviteCodesService
from app.conf import settings
from app.tgbot.admin.i18n import HandlersTexts
from app.tgbot.context import Context
from app.tgbot.dishka import inject

logger = structlog.get_logger()


@inject
async def generate_invites(
    update: Update,
    context: Context,
    admin: FromDishka[TGAdminUser],
    chat: FromDishka[Chat],
    invite_svc: FromDishka[TGInviteCodesService],
    texts: FromDishka[HandlersTexts],
) -> None:
    await _generate_invites(chat, admin, invite_svc, texts, amount=10, uses=1)


@inject
async def generate_invite_1(
    update: Update,
    context: Context,
    admin: FromDishka[TGAdminUser],
    chat: FromDishka[Chat],
    invite_svc: FromDishka[TGInviteCodesService],
    texts: FromDishka[HandlersTexts],
) -> None:
    await _generate_invites(chat, admin, invite_svc, texts, amount=1, uses=1)


@inject
async def generate_invite_10(
    update: Update,
    context: Context,
    admin: FromDishka[TGAdminUser],
    chat: FromDishka[Chat],
    invite_svc: FromDishka[TGInviteCodesService],
    texts: FromDishka[HandlersTexts],
) -> None:
    await _generate_invites(chat, admin, invite_svc, texts, amount=1, uses=10)


@inject
async def generate_invite_30(
    update: Update,
    context: Context,
    admin: FromDishka[TGAdminUser],
    chat: FromDishka[Chat],
    invite_svc: FromDishka[TGInviteCodesService],
    texts: FromDishka[HandlersTexts],
) -> None:
    await _generate_invites(chat, admin, invite_svc, texts, amount=1, uses=30)


async def _generate_invites(
    chat: Chat,
    admin: TGAdminUser,
    invite_svc: TGInviteCodesService,
    texts: HandlersTexts,
    *,
    amount: int,
    uses: int,
) -> None:
    logger.info("Generating invites", tg_user_id=admin.tg_id, amount=amount, uses=uses)
    invites = await invite_svc.create(
        amount=amount, uses=uses, tg_user_id=admin.tg_id, is_created_by_admin=True
    )

    invites_str = "\n".join(
        f'{i + 1}. <a href="https://t.me/{settings.TGBOT_NAME}?start={invite.code}">https://t.me/{settings.TGBOT_NAME}?start={invite.code}</a>'
        for i, invite in enumerate(invites)
    )
    await chat.send_message(
        text=f"<b>{texts.generate_invites.header}</b>\n\n{invites_str}",
        parse_mode=ParseMode.HTML,
    )
