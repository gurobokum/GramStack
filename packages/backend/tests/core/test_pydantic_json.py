from sqlalchemy import sql

from app.credits.models import CreditsPurchase
from app.db import AsyncSessionMaker


async def test_none_is_stored_as_sql_null(db_session_maker: AsyncSessionMaker) -> None:
    """
    `metadata` is declared with none_as_null, so None must reach postgres as SQL
    NULL, not as a JSON `null` value.
    """
    async with db_session_maker() as session, session.begin():
        await session.execute(
            sql.insert(CreditsPurchase).values(
                credits_amount=1, package_name="test", metadata_=None
            )
        )
        result = await session.execute(
            sql.select(sql.func.count())
            .select_from(CreditsPurchase)
            .filter(CreditsPurchase.metadata_.is_(None))
        )

    assert result.scalar_one() == 1
