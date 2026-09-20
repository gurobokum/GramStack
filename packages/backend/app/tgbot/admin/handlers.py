from telegram.ext import CommandHandler

from app.conf import settings
from app.tgbot.admin.generate_invites import (
    generate_invite_1,
    generate_invite_10,
    generate_invite_30,
    generate_invites,
)
from app.tgbot.routing import Handlers

handlers = Handlers(admin_only=True)

if settings.TGBOT_REQUIRES_INVITE:
    handlers.commands.extend(
        [
            CommandHandler("generate_invites", generate_invites),
            CommandHandler("generate_invite_1", generate_invite_1),
            CommandHandler("generate_invite_10", generate_invite_10),
            CommandHandler("generate_invite_30", generate_invite_30),
        ]
    )
