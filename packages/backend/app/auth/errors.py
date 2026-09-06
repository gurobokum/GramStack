from app.core.errors import AppError


class InvalidInviteCodeError(AppError):
    message = "Invalid invite code"
    code = "invalid_invite_code"


class InsufficientCreditsError(AppError):
    message = "Insufficient credits"
    code = "insufficient_credits"


class CreditsLockExpiredError(AppError):
    message = "Credits lock is no longer active"
    code = "credits_lock_expired"
