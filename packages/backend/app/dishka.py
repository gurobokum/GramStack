from collections.abc import Callable, Coroutine
from typing import Any

from dishka import AsyncContainer, Provider, Scope, provide
from dishka.integrations.base import wrap_injection
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.services import TGInviteCodesService, TGUserService
from app.credits.services import CreditsPurchaseService, CreditsService


def inject(
    container: AsyncContainer,
    provide_context: Callable[[tuple[Any, ...], dict[str, Any]], dict[Any, Any]],
    func: Callable[..., Coroutine[Any, Any, Any]],
) -> Callable[..., Coroutine[Any, Any, Any]]:
    return wrap_injection(
        func=func,
        is_async=True,
        container_getter=lambda *_: container,
        manage_scope=True,
        provide_context=provide_context,
    )


class ServicesProvider(Provider):
    scope = Scope.REQUEST

    @provide
    async def get_user_service(self, db_session: AsyncSession) -> TGUserService:
        return TGUserService(db_session)

    @provide
    async def get_invite_codes_service(
        self, db_session: AsyncSession
    ) -> TGInviteCodesService:
        return TGInviteCodesService(db_session)

    @provide
    async def get_credits_service(self, db_session: AsyncSession) -> CreditsService:
        return CreditsService(db_session)

    @provide
    async def get_credits_purchase_service(
        self, db_session: AsyncSession
    ) -> CreditsPurchaseService:
        return CreditsPurchaseService(db_session)
