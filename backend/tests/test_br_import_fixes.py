"""Epic 4B — Brazilian import pipeline fixes (regression)."""

from __future__ import annotations

import uuid
from datetime import date
from decimal import Decimal
from pathlib import Path

import pytest
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.account import Account
from app.models.transaction import Transaction
from app.models.user import User
from app.models.workspace import Workspace
from app.schemas.transaction import TransactionImport
from app.services.import_service import (
    CreditCardAmountSemanticsError,
    compute_import_mac,
    import_transactions,
    parse_csv,
    parse_ofx,
    verify_import_mac,
)
from app.services.transaction_classification import classify_orm
from app.services.transaction_service import fetch_counterpart_account_types

FIXTURES = Path(__file__).parent / "fixtures" / "br"


def _load(name: str) -> bytes:
    return (FIXTURES / name).read_bytes()


async def _account(
    session: AsyncSession,
    user: User,
    name: str,
    *,
    account_type: str = "checking",
) -> Account:
    acc = Account(
        id=uuid.uuid4(),
        user_id=user.id,
        name=name,
        type=account_type,
        balance=Decimal("0"),
        currency="BRL",
    )
    session.add(acc)
    await session.commit()
    await session.refresh(acc)
    return acc


@pytest.mark.asyncio
async def test_scenario_c_d_identical_purchases_and_reimport(
    session: AsyncSession, test_user: User, test_workspace: Workspace
):
    acc = await _account(session, test_user, "Scen CD")
    raw = (
        b"date,description,amount\n"
        b"2026-09-01,SUPERMERCADO,-100.00\n"
        b"2026-09-01,SUPERMERCADO,-100.00\n"
    )
    rows, _ = parse_csv(raw)
    i1, _, _, _ = await import_transactions(
        session, test_workspace.id, test_user.id, acc.id, rows,
        source="import", detected_format="csv",
    )
    assert i1 == 2
    rows2, _ = parse_csv(raw)
    i2, s2, _, _ = await import_transactions(
        session, test_workspace.id, test_user.id, acc.id, rows2,
        source="import", detected_format="csv",
    )
    assert i2 == 0 and s2 == 2
    assert await session.scalar(
        select(func.count()).select_from(Transaction).where(Transaction.account_id == acc.id)
    ) == 2


@pytest.mark.asyncio
async def test_scenario_e_cp1252_accents(
    session: AsyncSession, test_user: User, test_workspace: Workspace
):
    content = "date,description,amount\n2026-09-01,SUPERMERCADO SÃO JOSÉ,-10.00\n".encode(
        "cp1252"
    )
    txs, failed = parse_csv(content)
    assert failed == []
    assert "SÃO JOSÉ" in txs[0].description
    acc = await _account(session, test_user, "Enc")
    imported, _, _, _ = await import_transactions(
        session, test_workspace.id, test_user.id, acc.id, txs,
        source="import", detected_format="csv",
    )
    assert imported == 1


def test_scenario_f_brl_monetary_and_dates():
    txs, failed = parse_csv(_load("br_semicolon.csv"), date_format="DD/MM/YYYY")
    assert failed == []
    assert txs[0].amount == Decimal("1234.56")
    assert txs[0].date == date(2026, 9, 1)
    dash = b"date,description,amount\n01-09-2026,LOJA,-1.00\n"
    txs2, _ = parse_csv(dash, date_format="DD-MM-YYYY")
    assert txs2[0].date == date(2026, 9, 1)


@pytest.mark.asyncio
async def test_scenario_g_h_credit_card_amount_semantics(
    session: AsyncSession, test_user: User, test_workspace: Workspace
):
    card = await _account(session, test_user, "CC Sem", account_type="credit_card")
    csv = (
        b"date,description,amount\n"
        b"2026-09-01,SUPERMERCADO,350.00\n"
        b"2026-09-02,POSTO,280.00\n"
        b"2026-09-03,NETFLIX,55.00\n"
    )
    rows, _ = parse_csv(csv)
    assert all(r.type == "credit" for r in rows)

    with pytest.raises(CreditCardAmountSemanticsError):
        await import_transactions(
            session, test_workspace.id, test_user.id, card.id, rows,
            source="import", detected_format="csv",
        )

    rows2, _ = parse_csv(csv)
    imported, _, _, _ = await import_transactions(
        session, test_workspace.id, test_user.id, card.id, rows2,
        source="import", detected_format="csv",
        amount_semantics="expenses_positive",
    )
    assert imported == 3
    result = await session.execute(
        select(Transaction).where(Transaction.account_id == card.id)
    )
    assert {t.type for t in result.scalars().all()} == {"debit"}


@pytest.mark.asyncio
async def test_scenario_i_j_import_mac(
    session: AsyncSession, test_user: User, test_workspace: Workspace
):
    rows, _ = parse_csv(
        b"date,description,amount\n2026-09-01,CAFE,-10.00\n"
    )
    mac = compute_import_mac(rows)
    assert verify_import_mac(rows, mac)
    tampered = [
        TransactionImport(
            description=rows[0].description,
            amount=Decimal("99.00"),
            date=rows[0].date,
            type=rows[0].type,
            external_id=rows[0].external_id,
        )
    ]
    assert not verify_import_mac(tampered, mac)
    # Legacy clients without mac still allowed
    assert verify_import_mac(tampered, None)


@pytest.mark.asyncio
async def test_scenario_a_own_transfer_pairs(
    session: AsyncSession, test_user: User, test_workspace: Workspace
):
    a = await _account(session, test_user, "Bank A")
    b = await _account(session, test_user, "Bank B")
    rows = parse_ofx(_load("bank_own_transfer_and_noise.ofx"))
    out_leg = [r for r in rows if r.external_id == "BRTEST-FITID-OWN-OUT-001"]
    in_leg = [r for r in rows if r.external_id == "BRTEST-FITID-OWN-IN-001"]
    await import_transactions(
        session, test_workspace.id, test_user.id, a.id, out_leg,
        source="import", detected_format="ofx",
    )
    await import_transactions(
        session, test_workspace.id, test_user.id, b.id, in_leg,
        source="import", detected_format="ofx",
    )
    result = await session.execute(
        select(Transaction).where(Transaction.account_id.in_([a.id, b.id]))
    )
    txs = list(result.scalars().all())
    assert len(txs) == 2
    assert txs[0].transfer_pair_id and txs[0].transfer_pair_id == txs[1].transfer_pair_id


@pytest.mark.asyncio
async def test_scenario_b_card_purchases_and_payment_pnl(
    session: AsyncSession, test_user: User, test_workspace: Workspace
):
    bank = await _account(session, test_user, "Bank Pay")
    card = await _account(session, test_user, "Card Pay", account_type="credit_card")
    # Four purchases totaling 805.90 as expenses (signed negative in fixture)
    purchases, _ = parse_csv(_load("credit_card_purchases.csv"))
    assert sum(p.amount for p in purchases) == Decimal("805.90")
    assert all(p.type == "debit" for p in purchases)
    await import_transactions(
        session, test_workspace.id, test_user.id, card.id, purchases,
        source="import", detected_format="csv",
    )
    # Bill payment pair at 805.00 (fixture amounts) — P&L must not double-count
    bank_pay = parse_ofx(_load("bank_card_payment.ofx"))
    card_pay, _ = parse_csv(_load("credit_card_payment.csv"))
    await import_transactions(
        session, test_workspace.id, test_user.id, bank.id, bank_pay,
        source="import", detected_format="ofx",
    )
    await import_transactions(
        session, test_workspace.id, test_user.id, card.id, card_pay,
        source="import", detected_format="csv",
        amount_semantics="signed",
    )
    result = await session.execute(
        select(Transaction).where(Transaction.account_id.in_([bank.id, card.id]))
    )
    txs = list(result.scalars().all())
    counterparts = await fetch_counterpart_account_types(session, txs)
    classes = [classify_orm(t, counterparts.get(t.id)) for t in txs]
    assert classes.count("card_payment") == 2
    expense_debits = [
        t for t in txs
        if t.account_id == card.id and t.type == "debit" and t.transfer_pair_id is None
    ]
    assert sum(t.amount for t in expense_debits) == Decimal("805.90")


@pytest.mark.asyncio
async def test_installments_same_day_different_parcel_labels(
    session: AsyncSession, test_user: User, test_workspace: Workspace
):
    card = await _account(session, test_user, "CC Parc", account_type="credit_card")
    rows = [
        TransactionImport(
            description="LOJA EXEMPLO 01/10",
            amount=Decimal("199.90"),
            date=date(2026, 9, 5),
            type="debit",
        ),
        TransactionImport(
            description="LOJA EXEMPLO 02/10",
            amount=Decimal("199.90"),
            date=date(2026, 9, 5),
            type="debit",
        ),
        TransactionImport(
            description="LOJA EXEMPLO 03/10",
            amount=Decimal("199.90"),
            date=date(2026, 9, 5),
            type="debit",
        ),
    ]
    imported, skipped, _, _ = await import_transactions(
        session, test_workspace.id, test_user.id, card.id, rows,
        source="import", detected_format="csv",
    )
    assert imported == 3 and skipped == 0


@pytest.mark.asyncio
async def test_fitid_path_unchanged(
    session: AsyncSession, test_user: User, test_workspace: Workspace
):
    acc = await _account(session, test_user, "FITID OK")
    txs = parse_ofx(_load("bank_checking_synth.ofx"))
    assert all(
        t.external_id and not t.external_id.startswith("IMP-")
        for t in txs
    )
    i1, _, _, _ = await import_transactions(
        session, test_workspace.id, test_user.id, acc.id, txs,
        source="import", detected_format="ofx",
    )
    i2, s2, _, _ = await import_transactions(
        session, test_workspace.id, test_user.id, acc.id, txs,
        source="import", detected_format="ofx",
    )
    assert i1 == 5 and i2 == 0 and s2 == 5
