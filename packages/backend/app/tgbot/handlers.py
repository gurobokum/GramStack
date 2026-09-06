import structlog
from dishka import FromDishka
from telegram import Chat, Update, WebAppInfo
from telegram.constants import ChatMemberStatus
from telegram.ext import ChatMemberHandler, CommandHandler

from app.auth.errors import InvalidInviteCodeError
from app.auth.services import TGUserService
from app.conf import settings
from app.core.errors import AppError, UserIsBannedError
from app.posthog import PostHogEvent, posthog
from app.tgbot.admin.handlers import handlers as admin_handlers
from app.tgbot.context import Context
from app.tgbot.dishka import inject
from app.tgbot.i18n import HandlersTexts
from app.tgbot.utils import extract_user_data, get_invite_code, keyboard

logger = structlog.get_logger()


@inject
async def start(
    update: Update,
    context: Context,
    texts: FromDishka[HandlersTexts],
    chat: FromDishka[Chat],
    user_svc: FromDishka[TGUserService],
) -> None:
    user_data = extract_user_data(update)
    if user_data is None:
        raise AppError("User data is None", chat_id=chat.id)

    user = await user_svc.get_user_and_update(user_data)
    if not user:
        invite_code = get_invite_code(context)
        try:
            user = await user_svc.create(user_data, invite_code=invite_code)
        except InvalidInviteCodeError as e:
            logger.exception(e)
            await chat.send_message(
                text=texts.start.welcome_text,
            )
            return
        posthog.capture(
            user.tg_id,
            PostHogEvent.SIGNED_UP,
            {"$set": {"username": user.username}},
        )
        text = texts.start.welcome_text
    else:
        text = texts.start.welcome_back_text

    posthog.capture(user.tg_id, PostHogEvent.STARTED)
    await chat.send_message(
        text=text,
        reply_markup=keyboard(
            [(texts.start.button_setup, WebAppInfo(settings.MINIAPP_URL))]
        ),
    )


@inject
async def signin_middleware(
    update: Update,
    context: Context,
    user_svc: FromDishka[TGUserService],
) -> None:
    """
    Runs before every handler (group -1): drops updates from admin-blocked
    users and clears is_bot_blocked when such a user writes to the bot again.
    """
    user_data = extract_user_data(update)
    if not user_data:
        return

    user = await user_svc.get_user(user_data.tg_id)
    if not user:
        return

    if user.is_banned:
        raise UserIsBannedError

    if user.is_bot_blocked and await user_svc.mark_bot_unblocked(user.tg_id):
        posthog.capture(user.tg_id, PostHogEvent.USER_UNBLOCKED_BOT)


@inject
async def track_bot_block(
    update: Update,
    context: Context,
    user_svc: FromDishka[TGUserService],
) -> None:
    member = update.my_chat_member
    if not member or member.chat.type != Chat.PRIVATE:
        return

    tg_id = member.from_user.id
    status = member.new_chat_member.status
    if status == ChatMemberStatus.BANNED and await user_svc.mark_bot_blocked(tg_id):
        posthog.capture(tg_id, PostHogEvent.USER_BLOCKED_BOT)
    elif status == ChatMemberStatus.MEMBER and await user_svc.mark_bot_unblocked(tg_id):
        posthog.capture(tg_id, PostHogEvent.USER_UNBLOCKED_BOT)


handlers = [
    CommandHandler("start", start),
    ChatMemberHandler(track_bot_block, ChatMemberHandler.MY_CHAT_MEMBER),
    *admin_handlers,
]
