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
