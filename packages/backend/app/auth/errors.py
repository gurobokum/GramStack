from app.core.errors import AppError


class InvalidInviteCodeError(AppError):
    message = "Invalid invite code"
    code = "invalid_invite_code"
