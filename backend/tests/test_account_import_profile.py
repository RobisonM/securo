"""Account import_profile + Sicredi-style CSV preamble (header_row)."""
from decimal import Decimal
from pathlib import Path

import pytest

from app.schemas.account import AccountCreate, AccountImportProfile, AccountUpdate
from app.services import account_service
from app.services.import_service import (
    detect_csv_columns,
    merge_import_profile,
    normalize_amount,
    parse_csv,
)

FIXTURES = Path(__file__).parent / "fixtures" / "br"


def _load(name: str) -> bytes:
    return (FIXTURES / name).read_bytes()


# Sicredi fatura: summary preamble + signed amounts (purchases +, payments -).
# flip_amount turns purchases into debits and payments into credits on the card.
SICREDI_PROFILE = {
    "header_row": 20,
    "delimiter": ";",
    "date_format": "DD/MM/YYYY",
    "flip_amount": True,
    "column_mapping": {
        "date": "Data",
        "description": "Descrição",
        "amount": "Valor",
        "installment": "Parcela",
        "cardholder": "Nome",
    },
}


def test_normalize_amount_strips_negative_brl_prefix():
    assert normalize_amount("-R$ 16.647,70") == "-16647.70"
    assert normalize_amount("R$ 3,82") == "3.82"


def test_detect_csv_columns_with_header_row_skips_summary():
    cols = detect_csv_columns(
        _load("sicredi_fatura_summary.csv"),
        header_row=20,
        delimiter=";",
    )
    assert cols[0] == "Data"
    assert "Descrição" in cols
    assert "Valor" in cols
    assert "Associado" not in cols


def test_parse_sicredi_fatura_with_profile():
    rows, failed = parse_csv(
        _load("sicredi_fatura_summary.csv"),
        date_format="DD/MM/YYYY",
        header_row=20,
        delimiter=";",
        flip_amount=True,
        column_mapping=SICREDI_PROFILE["column_mapping"],
    )
    assert failed == []
    assert len(rows) == 6
    assert rows[0].description == "SUPERMERCADO EXEMPLO"
    assert rows[0].amount == Decimal("98.42")
    assert rows[0].type == "debit"
    assert rows[0].cardholder == "Exemplo Titular"
    assert rows[2].installment_number == 1
    assert rows[2].total_installments == 3
    assert rows[2].cardholder == "Exemplo Titular"
    payment = next(r for r in rows if "Pag Fat" in r.description)
    assert payment.amount == Decimal("400.00")
    assert payment.type == "credit"
    credit = next(r for r in rows if "Credito Anuidade" in r.description)
    assert credit.type == "credit"


def test_parse_sicredi_without_header_row_fails():
    with pytest.raises(ValueError):
        parse_csv(_load("sicredi_fatura_summary.csv"), delimiter=";")


def test_merge_import_profile_request_overrides_account():
    merged = merge_import_profile(
        SICREDI_PROFILE,
        header_row=21,
        date_format="YYYY-MM-DD",
    )
    assert merged["header_row"] == 21
    assert merged["date_format"] == "YYYY-MM-DD"
    assert merged["delimiter"] == ";"
    assert merged["flip_amount"] is True
    assert merged["column_mapping"]["amount"] == "Valor"


@pytest.mark.asyncio
async def test_account_persists_import_profile(session, test_user, test_workspace):
    profile = AccountImportProfile(**SICREDI_PROFILE)
    account = await account_service.create_account(
        session,
        test_workspace.id,
        test_user.id,
        AccountCreate(
            name="Sicredi Mastercard",
            type="credit_card",
            balance=Decimal("0"),
            currency="BRL",
            import_profile=profile,
        ),
    )
    assert account.import_profile["header_row"] == 20
    assert account.import_profile["delimiter"] == ";"
    assert account.import_profile["flip_amount"] is True

    serialized = account_service.serialize_account(account, Decimal("0"), None)
    assert serialized["import_profile"]["header_row"] == 20

    updated = await account_service.update_account(
        session,
        account.id,
        test_workspace.id,
        AccountUpdate(import_profile=None),
    )
    assert updated is not None
    assert updated.import_profile is None


@pytest.mark.asyncio
async def test_preview_uses_account_import_profile(client, auth_headers):
    create = await client.post(
        "/api/accounts",
        headers=auth_headers,
        json={
            "name": "Cartão Sicredi",
            "type": "credit_card",
            "balance": 0,
            "currency": "BRL",
            "import_profile": SICREDI_PROFILE,
        },
    )
    assert create.status_code == 201, create.text
    account_id = create.json()["id"]
    assert create.json()["import_profile"]["header_row"] == 20

    resp = await client.post(
        "/api/transactions/import/preview",
        headers=auth_headers,
        files={"file": ("sicredi.csv", _load("sicredi_fatura_summary.csv"), "text/csv")},
        data={"account_id": account_id},
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["detected_format"] == "csv"
    assert body["parse_error"] is None
    assert len(body["transactions"]) == 6
    assert body["csv_columns"][0] == "Data"
    purchase = next(t for t in body["transactions"] if t["description"] == "SUPERMERCADO EXEMPLO")
    assert purchase["type"] == "debit"
    payment = next(t for t in body["transactions"] if "Pag Fat" in t["description"])
    assert payment["type"] == "credit"


@pytest.mark.asyncio
async def test_import_with_profile_lands_purchases_as_expense(client, auth_headers):
    create = await client.post(
        "/api/accounts",
        headers=auth_headers,
        json={
            "name": "Cartão Sicredi 2",
            "type": "credit_card",
            "balance": 0,
            "currency": "BRL",
            "import_profile": SICREDI_PROFILE,
        },
    )
    assert create.status_code == 201, create.text
    account_id = create.json()["id"]

    preview = await client.post(
        "/api/transactions/import/preview",
        headers=auth_headers,
        files={"file": ("sicredi.csv", _load("sicredi_fatura_summary.csv"), "text/csv")},
        data={"account_id": account_id},
    )
    assert preview.status_code == 200
    pdata = preview.json()

    resp = await client.post(
        "/api/transactions/import",
        headers=auth_headers,
        json={
            "account_id": account_id,
            "transactions": pdata["transactions"],
            "filename": "sicredi.csv",
            "detected_format": "csv",
            "import_mac": pdata["import_mac"],
        },
    )
    assert resp.status_code == 201, resp.text
    assert resp.json()["imported"] == 6

    purchase = next(t for t in pdata["transactions"] if t["description"] == "SUPERMERCADO EXEMPLO")
    assert purchase["type"] == "debit"
    payment = next(t for t in pdata["transactions"] if "Pag Fat" in t["description"])
    assert payment["type"] == "credit"
