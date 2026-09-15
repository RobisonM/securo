"""Epic 5A — personal dashboard financial metrics (invariants + new endpoints)."""

from __future__ import annotations

import uuid
from datetime import date, datetime, timezone
from decimal import Decimal

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.account import Account
from app.models.category import Category
from app.models.payee import Payee
from app.models.transaction import Transaction
from app.models.user import User
from app.models.workspace import Workspace, WorkspaceMember
from app.services.dashboard_service import (
    get_credit_cards_summary,
    get_monthly_trend,
    get_spending_by_category,
    get_summary,
    get_top_expenses,
    get_top_merchants,
)

MONTH = date(2026, 9, 1)
D = date(2026, 9, 15)


async def _account(
    session: AsyncSession,
    user_id: uuid.UUID,
    name: str,
    *,
    account_type: str = "checking",
    credit_limit: Decimal | None = None,
) -> Account:
    acc = Account(
        id=uuid.uuid4(),
        user_id=user_id,
        name=name,
        type=account_type,
        balance=Decimal("0"),
        currency="BRL",
        credit_limit=credit_limit,
    )
    session.add(acc)
    await session.commit()
    await session.refresh(acc)
    return acc


async def _category(session: AsyncSession, user_id: uuid.UUID, name: str) -> Category:
    cat = Category(
        id=uuid.uuid4(),
        user_id=user_id,
        name=name,
        icon="tag",
        color="#000000",
    )
    session.add(cat)
    await session.commit()
    await session.refresh(cat)
    return cat


async def _txn(
    session: AsyncSession,
    user_id: uuid.UUID,
    account_id: uuid.UUID,
    *,
    description: str,
    amount: Decimal,
    txn_type: str,
    txn_date: date = D,
    category_id: uuid.UUID | None = None,
    transfer_pair_id: uuid.UUID | None = None,
    exclude_from_pnl: bool = False,
    is_ignored: bool = False,
    payee_id: uuid.UUID | None = None,
    payee: str | None = None,
) -> Transaction:
    tx = Transaction(
        id=uuid.uuid4(),
        user_id=user_id,
        account_id=account_id,
        description=description,
        amount=amount,
        date=txn_date,
        effective_date=txn_date,
        type=txn_type,
        source="manual",
        currency="BRL",
        category_id=category_id,
        transfer_pair_id=transfer_pair_id,
        exclude_from_pnl=exclude_from_pnl,
        is_ignored=is_ignored,
        payee_id=payee_id,
        payee=payee,
        status="posted",
        created_at=datetime.now(timezone.utc),
    )
    session.add(tx)
    await session.commit()
    await session.refresh(tx)
    return tx


async def _seed_base_month(
    session: AsyncSession, user_id: uuid.UUID
) -> tuple[Account, dict[str, Category]]:
    checking = await _account(session, user_id, "Conta")
    cats = {
        "receita": await _category(session, user_id, "Receita"),
        "alim": await _category(session, user_id, "Alimentação"),
        "transp": await _category(session, user_id, "Transporte"),
        "assin": await _category(session, user_id, "Assinaturas"),
    }
    await _txn(
        session, user_id, checking.id,
        description="SALÁRIO", amount=Decimal("8000.00"), txn_type="credit",
        category_id=cats["receita"].id,
    )
    await _txn(
        session, user_id, checking.id,
        description="SUPERMERCADO", amount=Decimal("1200.00"), txn_type="debit",
        category_id=cats["alim"].id,
    )
    await _txn(
        session, user_id, checking.id,
        description="COMBUSTÍVEL", amount=Decimal("600.00"), txn_type="debit",
        category_id=cats["transp"].id,
    )
    await _txn(
        session, user_id, checking.id,
        description="RESTAURANTE", amount=Decimal("300.00"), txn_type="debit",
        category_id=cats["alim"].id,
    )
    await _txn(
        session, user_id, checking.id,
        description="NETFLIX", amount=Decimal("55.00"), txn_type="debit",
        category_id=cats["assin"].id,
    )
    return checking, cats


@pytest.mark.asyncio
async def test_income_expense_net_base_month(
    session: AsyncSession, test_user: User, test_workspace: Workspace
):
    await _seed_base_month(session, test_user.id)
    summary = await get_summary(session, test_workspace.id, test_user.id, month=MONTH)
    assert summary.monthly_income == pytest.approx(8000.0)
    assert summary.monthly_expenses == pytest.approx(2155.0)
    assert summary.monthly_net == pytest.approx(5845.0)
    assert summary.monthly_net_primary == pytest.approx(5845.0)


@pytest.mark.asyncio
async def test_transfer_excluded_from_pnl(
    session: AsyncSession, test_user: User, test_workspace: Workspace
):
    await _seed_base_month(session, test_user.id)
    itau = await _account(session, test_user.id, "Itaú")
    nubank = await _account(session, test_user.id, "Nubank")
    pair = uuid.uuid4()
    await _txn(
        session, test_user.id, itau.id,
        description="PIX OUT", amount=Decimal("2000.00"), txn_type="debit",
        transfer_pair_id=pair,
    )
    await _txn(
        session, test_user.id, nubank.id,
        description="PIX IN", amount=Decimal("2000.00"), txn_type="credit",
        transfer_pair_id=pair,
    )
    summary = await get_summary(session, test_workspace.id, test_user.id, month=MONTH)
    assert summary.monthly_income == pytest.approx(8000.0)
    assert summary.monthly_expenses == pytest.approx(2155.0)
    assert summary.monthly_net == pytest.approx(5845.0)


@pytest.mark.asyncio
async def test_card_payment_not_double_counted(
    session: AsyncSession, test_user: User, test_workspace: Workspace
):
    bank = await _account(session, test_user.id, "Banco")
    card = await _account(session, test_user.id, "Cartão", account_type="credit_card")
    alim = await _category(session, test_user.id, "Alimentação")
    transp = await _category(session, test_user.id, "Transporte")
    assin = await _category(session, test_user.id, "Assinaturas")
    for desc, amt, cat in [
        ("SUPERMERCADO", Decimal("1200.00"), alim.id),
        ("COMBUSTÍVEL", Decimal("600.00"), transp.id),
        ("RESTAURANTE", Decimal("300.00"), alim.id),
        ("NETFLIX", Decimal("55.00"), assin.id),
    ]:
        await _txn(
            session, test_user.id, card.id,
            description=desc, amount=amt, txn_type="debit", category_id=cat,
        )
    pair = uuid.uuid4()
    await _txn(
        session, test_user.id, bank.id,
        description="PAGAMENTO CARTAO", amount=Decimal("2155.00"), txn_type="debit",
        transfer_pair_id=pair,
    )
    await _txn(
        session, test_user.id, card.id,
        description="PAGAMENTO FATURA", amount=Decimal("2155.00"), txn_type="credit",
        transfer_pair_id=pair,
    )
    summary = await get_summary(session, test_workspace.id, test_user.id, month=MONTH)
    assert summary.monthly_expenses == pytest.approx(2155.0)
    assert summary.monthly_expenses != pytest.approx(4310.0)


@pytest.mark.asyncio
async def test_adjustment_and_ignored_excluded(
    session: AsyncSession, test_user: User, test_workspace: Workspace
):
    checking, cats = await _seed_base_month(session, test_user.id)
    await _txn(
        session, test_user.id, checking.id,
        description="AJUSTE", amount=Decimal("500.00"), txn_type="debit",
        category_id=cats["alim"].id, exclude_from_pnl=True,
    )
    await _txn(
        session, test_user.id, checking.id,
        description="IGNORED", amount=Decimal("400.00"), txn_type="debit",
        category_id=cats["alim"].id, is_ignored=True,
    )
    summary = await get_summary(session, test_workspace.id, test_user.id, month=MONTH)
    assert summary.monthly_expenses == pytest.approx(2155.0)


@pytest.mark.asyncio
async def test_uncategorized_in_expense_and_pending(
    session: AsyncSession, test_user: User, test_workspace: Workspace
):
    checking, _ = await _seed_base_month(session, test_user.id)
    await _txn(
        session, test_user.id, checking.id,
        description="LOJA DESCONHECIDA", amount=Decimal("100.00"), txn_type="debit",
    )
    summary = await get_summary(session, test_workspace.id, test_user.id, month=MONTH)
    assert summary.monthly_expenses == pytest.approx(2255.0)
    assert summary.pending_categorization == 1
    assert summary.pending_categorization_amount == pytest.approx(100.0)

    spending = await get_spending_by_category(
        session, test_workspace.id, test_user.id, month=MONTH
    )
    uncat = next(s for s in spending if s.category_id is None)
    assert uncat.category_name == "Sem categoria"
    assert uncat.total == pytest.approx(100.0)
    assert sum(s.total for s in spending) == pytest.approx(2255.0)


@pytest.mark.asyncio
async def test_category_breakdown_and_percentages(
    session: AsyncSession, test_user: User, test_workspace: Workspace
):
    await _seed_base_month(session, test_user.id)
    spending = await get_spending_by_category(
        session, test_workspace.id, test_user.id, month=MONTH
    )
    by_name = {s.category_name: s for s in spending}
    assert by_name["Alimentação"].total == pytest.approx(1500.0)
    assert by_name["Transporte"].total == pytest.approx(600.0)
    assert by_name["Assinaturas"].total == pytest.approx(55.0)
    total = sum(s.total for s in spending)
    assert total == pytest.approx(2155.0)
    assert sum(s.percentage for s in spending) == pytest.approx(100.0, abs=0.1)


async def _register_sqlite_to_char(session: AsyncSession) -> None:
    def _to_char(value, fmt):
        if value is None:
            return None
        return str(value)[:7]

    raw = await session.connection()

    def _install(dbapi_conn):
        dbapi_conn.create_function("to_char", 2, _to_char)

    await raw.run_sync(lambda conn: _install(conn.connection.dbapi_connection))


@pytest.mark.asyncio
async def test_monthly_trend_zero_fill_and_net(
    session: AsyncSession, test_user: User, test_workspace: Workspace
):
    await _register_sqlite_to_char(session)
    await _seed_base_month(session, test_user.id)
    today = date.today()
    month_start = today.replace(day=1)
    checking = await _account(session, test_user.id, "Trend Acc")
    await _txn(
        session, test_user.id, checking.id,
        description="NOW", amount=Decimal("10.00"), txn_type="debit",
        txn_date=today,
    )
    trend = await get_monthly_trend(session, test_workspace.id, test_user.id, months=3)
    assert len(trend) == 3
    assert all(hasattr(row, "net") for row in trend)
    keys = [row.month for row in trend]
    assert keys == sorted(keys)  # ascending
    assert f"{month_start.year:04d}-{month_start.month:02d}" in keys
    for row in trend:
        assert row.net == pytest.approx(row.income - row.expenses)


@pytest.mark.asyncio
async def test_top_expenses_excludes_non_pnl(
    session: AsyncSession, test_user: User, test_workspace: Workspace
):
    checking, cats = await _seed_base_month(session, test_user.id)
    pair = uuid.uuid4()
    await _txn(
        session, test_user.id, checking.id,
        description="TRANSFER BIG", amount=Decimal("9000.00"), txn_type="debit",
        transfer_pair_id=pair,
    )
    await _txn(
        session, test_user.id, checking.id,
        description="AJUSTE BIG", amount=Decimal("8000.00"), txn_type="debit",
        exclude_from_pnl=True,
    )
    top = await get_top_expenses(
        session, test_workspace.id, test_user.id, month=MONTH, limit=5
    )
    descs = [t.description for t in top]
    assert "SUPERMERCADO" in descs
    assert "TRANSFER BIG" not in descs
    assert "AJUSTE BIG" not in descs
    assert top[0].amount == pytest.approx(1200.0)


@pytest.mark.asyncio
async def test_top_merchants(
    session: AsyncSession, test_user: User, test_workspace: Workspace
):
    checking = await _account(session, test_user.id, "Merch Acc")
    payee = Payee(
        id=uuid.uuid4(),
        user_id=test_user.id,
        workspace_id=test_workspace.id,
        name="IFOOD",
    )
    session.add(payee)
    await session.commit()
    await _txn(
        session, test_user.id, checking.id,
        description="IFOOD *1", amount=Decimal("40.00"), txn_type="debit",
        payee_id=payee.id, payee="IFOOD",
    )
    await _txn(
        session, test_user.id, checking.id,
        description="IFOOD *2", amount=Decimal("60.00"), txn_type="debit",
        payee_id=payee.id, payee="IFOOD",
    )
    merchants = await get_top_merchants(
        session, test_workspace.id, test_user.id, month=MONTH, limit=10
    )
    assert merchants
    assert merchants[0].merchant == "IFOOD"
    assert merchants[0].amount == pytest.approx(100.0)
    assert merchants[0].transaction_count == 2


@pytest.mark.asyncio
async def test_credit_cards_summary(
    session: AsyncSession, test_user: User, test_workspace: Workspace
):
    await _account(
        session, test_user.id, "Visa",
        account_type="credit_card", credit_limit=Decimal("5000.00"),
    )
    cards = await get_credit_cards_summary(session, test_workspace.id, test_user.id)
    assert len(cards) == 1
    assert cards[0].name == "Visa"
    assert cards[0].credit_limit == pytest.approx(5000.0)
    assert cards[0].available_credit is not None


@pytest.mark.asyncio
async def test_decimal_precision_pennies(
    session: AsyncSession, test_user: User, test_workspace: Workspace
):
    checking = await _account(session, test_user.id, "Cents")
    await _txn(
        session, test_user.id, checking.id,
        description="A", amount=Decimal("0.10"), txn_type="debit",
    )
    await _txn(
        session, test_user.id, checking.id,
        description="B", amount=Decimal("0.20"), txn_type="debit",
    )
    await _txn(
        session, test_user.id, checking.id,
        description="C", amount=Decimal("0.30"), txn_type="debit",
    )
    summary = await get_summary(session, test_workspace.id, test_user.id, month=MONTH)
    assert summary.monthly_expenses == pytest.approx(0.60)


@pytest.mark.asyncio
async def test_empty_workspace_and_only_transfers(
    session: AsyncSession, test_user: User, test_workspace: Workspace
):
    empty = await get_summary(session, test_workspace.id, test_user.id, month=MONTH)
    assert empty.monthly_income == pytest.approx(0.0)
    assert empty.monthly_expenses == pytest.approx(0.0)
    assert empty.monthly_net == pytest.approx(0.0)

    a = await _account(session, test_user.id, "A")
    b = await _account(session, test_user.id, "B")
    pair = uuid.uuid4()
    await _txn(
        session, test_user.id, a.id,
        description="OUT", amount=Decimal("50.00"), txn_type="debit",
        transfer_pair_id=pair,
    )
    await _txn(
        session, test_user.id, b.id,
        description="IN", amount=Decimal("50.00"), txn_type="credit",
        transfer_pair_id=pair,
    )
    only_xfer = await get_summary(session, test_workspace.id, test_user.id, month=MONTH)
    assert only_xfer.monthly_income == pytest.approx(0.0)
    assert only_xfer.monthly_expenses == pytest.approx(0.0)


@pytest.mark.asyncio
async def test_workspace_isolation(
    session: AsyncSession, test_user: User, test_workspace: Workspace
):
    await _seed_base_month(session, test_user.id)

    other_ws = Workspace(id=uuid.uuid4(), name="Other", kind="personal")
    session.add(other_ws)
    session.add(
        WorkspaceMember(
            id=uuid.uuid4(),
            workspace_id=other_ws.id,
            user_id=test_user.id,
            role="owner",
        )
    )
    await session.commit()

    other_acc = Account(
        id=uuid.uuid4(),
        user_id=test_user.id,
        workspace_id=other_ws.id,
        name="Other Acc",
        type="checking",
        balance=Decimal("0"),
        currency="BRL",
    )
    session.add(other_acc)
    await session.commit()
    await _txn(
        session, test_user.id, other_acc.id,
        description="OTHER EXPENSE", amount=Decimal("9999.00"), txn_type="debit",
    )

    summary = await get_summary(session, test_workspace.id, test_user.id, month=MONTH)
    assert summary.monthly_expenses == pytest.approx(2155.0)

    spending = await get_spending_by_category(
        session, test_workspace.id, test_user.id, month=MONTH
    )
    assert sum(s.total for s in spending) == pytest.approx(2155.0)

    top = await get_top_expenses(
        session, test_workspace.id, test_user.id, month=MONTH
    )
    assert all(t.description != "OTHER EXPENSE" for t in top)

    merchants = await get_top_merchants(
        session, test_workspace.id, test_user.id, month=MONTH
    )
    assert all(m.merchant != "OTHER EXPENSE" for m in merchants)


@pytest.mark.asyncio
async def test_pending_excludes_ignored_and_adjustments(
    session: AsyncSession, test_user: User, test_workspace: Workspace
):
    checking = await _account(session, test_user.id, "Pend")
    await _txn(
        session, test_user.id, checking.id,
        description="REAL PENDING", amount=Decimal("70.00"), txn_type="debit",
    )
    await _txn(
        session, test_user.id, checking.id,
        description="IGNORED PENDING", amount=Decimal("80.00"), txn_type="debit",
        is_ignored=True,
    )
    await _txn(
        session, test_user.id, checking.id,
        description="ADJ PENDING", amount=Decimal("90.00"), txn_type="debit",
        exclude_from_pnl=True,
    )
    summary = await get_summary(session, test_workspace.id, test_user.id, month=MONTH)
    assert summary.pending_categorization == 1
    assert summary.pending_categorization_amount == pytest.approx(70.0)


@pytest.mark.asyncio
async def test_dashboard_api_contract(client, auth_headers, test_user, session, test_workspace):
    await _seed_base_month(session, test_user.id)
    month = MONTH.isoformat()

    r = await client.get(
        "/api/dashboard/summary", params={"month": month}, headers=auth_headers
    )
    assert r.status_code == 200
    body = r.json()
    assert "monthly_net" in body
    assert "monthly_net_primary" in body
    assert body["monthly_income"] == pytest.approx(8000.0)
    assert body["monthly_expenses"] == pytest.approx(2155.0)
    assert body["monthly_net"] == pytest.approx(5845.0)

    r = await client.get(
        "/api/dashboard/top-expenses", params={"month": month, "limit": 5}, headers=auth_headers
    )
    assert r.status_code == 200
    assert isinstance(r.json(), list)
    assert r.json()[0]["amount"] == pytest.approx(1200.0)

    r = await client.get(
        "/api/dashboard/top-merchants", params={"month": month}, headers=auth_headers
    )
    assert r.status_code == 200
    assert isinstance(r.json(), list)

    r = await client.get("/api/dashboard/credit-cards", headers=auth_headers)
    assert r.status_code == 200
    assert isinstance(r.json(), list)

    # monthly-trend uses Postgres to_char; covered in service tests with SQLite UDF.
