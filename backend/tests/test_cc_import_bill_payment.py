"""Credit-card statement import: payment date + parcela/titular."""
from datetime import date
from decimal import Decimal
from pathlib import Path

import pytest
from sqlalchemy import select

from app.models.transaction import Transaction
from app.schemas.account import AccountCreate
from app.services import account_service
from app.services.import_service import (
    import_transactions,
    parse_csv,
    parse_installment_label,
)

FIXTURES = Path(__file__).parent / "fixtures" / "br"


def test_parse_installment_label():
    assert parse_installment_label("(01/03)") == (1, 3)
    assert parse_installment_label("02/10") == (2, 10)
    assert parse_installment_label("") is None
    assert parse_installment_label("avista") is None


@pytest.mark.asyncio
async def test_cc_import_bill_payment_date_sets_effective_bill(
    session, test_user, test_workspace
):
    account = await account_service.create_account(
        session,
        test_workspace.id,
        test_user.id,
        AccountCreate(
            name="Cartão",
            type="credit_card",
            balance=Decimal("0"),
            currency="BRL",
        ),
    )
    rows, _ = parse_csv(
        (FIXTURES / "sicredi_fatura_summary.csv").read_bytes(),
        date_format="DD/MM/YYYY",
        header_row=20,
        delimiter=";",
        flip_amount=True,
        column_mapping={
            "date": "Data",
            "description": "Descrição",
            "amount": "Valor",
            "installment": "Parcela",
            "cardholder": "Nome",
        },
    )
    payment = date(2026, 9, 10)
    imported, _, _, _ = await import_transactions(
        session,
        test_workspace.id,
        test_user.id,
        account.id,
        rows,
        source="import",
        detected_format="csv",
        bill_payment_date=payment,
    )
    assert imported == 6

    result = await session.execute(
        select(Transaction).where(Transaction.account_id == account.id)
    )
    txs = list(result.scalars().all())
    purchase = next(t for t in txs if t.description == "SUPERMERCADO EXEMPLO")
    # Ledger date stays purchase date; bill payment drives dashboard bucketing.
    assert purchase.date == date(2026, 8, 26)
    assert purchase.effective_bill_date == payment
    assert purchase.effective_date == payment
    assert purchase.cardholder == "Exemplo Titular"

    parcel = next(t for t in txs if t.description == "LOJA PARCELADA")
    assert parcel.installment_number == 1
    assert parcel.total_installments == 3

    # Credits (pagamento / crédito anuidade) are fatura abatements — not P&L.
    payment_tx = next(t for t in txs if "Pag Fat" in t.description)
    assert payment_tx.type == "credit"
    assert payment_tx.exclude_from_pnl is True
    fee_credit = next(t for t in txs if "Credito Anuidade" in t.description)
    assert fee_credit.type == "credit"
    assert fee_credit.exclude_from_pnl is True
    # Purchases remain ordinary expenses (included in P&L).
    assert purchase.exclude_from_pnl is False
    assert purchase.type == "debit"


@pytest.mark.asyncio
async def test_cc_expenses_positive_keeps_negative_rows_as_credits(
    session, test_user, test_workspace
):
    """Mixed fatura CSV: positive = purchase, negative = abatement.

    expenses_positive must flip both directions so payments/refunds stay
    credits (and then exclude_from_pnl), not extra expenses.
    """
    account = await account_service.create_account(
        session,
        test_workspace.id,
        test_user.id,
        AccountCreate(
            name="Cartão Sem Flip",
            type="credit_card",
            balance=Decimal("0"),
            currency="BRL",
        ),
    )
    csv = (
        b"date,description,amount\n"
        b"2026-08-01,SUPERMERCADO,100.00\n"
        b"2026-08-02,PAGAMENTO FATURA,-80.00\n"
        b"2026-08-03,ESTORNO LOJA,-20.00\n"
    )
    rows, _ = parse_csv(csv)
    assert rows[0].type == "credit"  # positive before semantics
    assert rows[1].type == "debit"   # negative before semantics

    imported, _, _, _ = await import_transactions(
        session,
        test_workspace.id,
        test_user.id,
        account.id,
        rows,
        source="import",
        detected_format="csv",
        amount_semantics="expenses_positive",
    )
    assert imported == 3

    result = await session.execute(
        select(Transaction).where(Transaction.account_id == account.id)
    )
    by_desc = {t.description: t for t in result.scalars().all()}
    assert by_desc["SUPERMERCADO"].type == "debit"
    assert by_desc["SUPERMERCADO"].exclude_from_pnl is False
    assert by_desc["PAGAMENTO FATURA"].type == "credit"
    assert by_desc["PAGAMENTO FATURA"].exclude_from_pnl is True
    assert by_desc["ESTORNO LOJA"].type == "credit"
    assert by_desc["ESTORNO LOJA"].exclude_from_pnl is True


@pytest.mark.asyncio
async def test_cc_bill_total_nets_abatement_credits(
    session, test_user, test_workspace
):
    """Fatura total = purchases − credits even when credits are exclude_from_pnl."""
    from app.services import account_service as acct_svc

    account = await account_service.create_account(
        session,
        test_workspace.id,
        test_user.id,
        AccountCreate(
            name="Cartão Bill Net",
            type="credit_card",
            balance=Decimal("0"),
            currency="BRL",
        ),
    )
    csv = (
        b"date,description,amount\n"
        b"2026-09-05,COMPRA A,100.00\n"
        b"2026-09-06,COMPRA B,50.00\n"
        b"2026-09-07,CREDITO ANUIDADE,-30.00\n"
    )
    rows, _ = parse_csv(csv, flip_amount=True)
    await import_transactions(
        session,
        test_workspace.id,
        test_user.id,
        account.id,
        rows,
        source="import",
        detected_format="csv",
    )
    summary = await acct_svc.get_account_summary(
        session,
        account.id,
        test_workspace.id,
        date_from=date(2026, 9, 1),
        date_to=date(2026, 9, 30),
    )
    # 100 + 50 − 30 = 120 on the bill; credits must not vanish from the fatura.
    assert Decimal(str(summary["monthly_expenses"])) == Decimal("120.00")
