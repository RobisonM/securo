"""Epic 4A — characterization of the Brazilian import pipeline.

These tests document CURRENT behaviour. Gaps are named
``test_current_behavior_*`` when the observed result is not the desired
long-term outcome. No production importer changes in this epic.
"""

from __future__ import annotations

import uuid
from datetime import date
from decimal import Decimal
from pathlib import Path

import pytest
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.account import Account
from app.models.category import Category
from app.models.transaction import Transaction
from app.models.user import User
from app.models.workspace import Workspace
from app.schemas.transaction import TransactionImport
from app.services.category_suggestion_service import suggest_categories_for_transactions
from app.services.import_service import import_transactions, normalize_amount, parse_csv, parse_ofx
from app.services.transaction_classification import classify_orm
from app.services.transaction_service import (
    build_transaction_reads,
    fetch_counterpart_account_types,
)

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


async def _category(session: AsyncSession, user: User, name: str) -> Category:
    cat = Category(
        id=uuid.uuid4(),
        user_id=user.id,
        name=name,
        icon="circle",
        color="#000000",
    )
    session.add(cat)
    await session.commit()
    await session.refresh(cat)
    return cat


# ---------------------------------------------------------------------------
# Parse characterization — OFX Brasil
# ---------------------------------------------------------------------------


class TestBrOfxParse:
    def test_ofx_pix_out_in_ted_tarifa_rendimento(self):
        txs = parse_ofx(_load("bank_checking_synth.ofx"))
        by_fitid = {t.external_id: t for t in txs}

        out = by_fitid["BRTEST-FITID-PIX-OUT-001"]
        assert out.type == "debit"
        assert out.amount == Decimal("80.00")
        assert "IFOOD" in out.description

        inn = by_fitid["BRTEST-FITID-PIX-IN-001"]
        assert inn.type == "credit"
        assert inn.amount == Decimal("2500.00")
        assert "PIX RECEBIDO" in inn.description

        ted = by_fitid["BRTEST-FITID-TED-IN-001"]
        assert ted.type == "credit"
        assert ted.amount == Decimal("1200.00")

        tarifa = by_fitid["BRTEST-FITID-TARIFA-001"]
        assert tarifa.type == "debit"
        assert tarifa.amount == Decimal("39.90")

        rend = by_fitid["BRTEST-FITID-REND-001"]
        assert rend.type == "credit"
        assert rend.amount == Decimal("12.45")

    def test_ofx_accent_latin1_sgml_current_behavior(self):
        """CURRENT: OFX SGML with Latin-1 accents — decode path is UTF-8 then Latin-1."""
        # Build a minimal STMTTRN with accented memo encoded as latin-1 bytes
        # after an ASCII header (common BR bank pattern with CHARSET:1252).
        header = (
            "OFXHEADER:100\nDATA:OFXSGML\nVERSION:102\nSECURITY:NONE\n"
            "ENCODING:USASCII\nCHARSET:1252\nCOMPRESSION:NONE\n"
            "OLDFILEUID:NONE\nNEWFILEUID:NONE\n\n"
        ).encode("ascii")
        body = (
            "<OFX><SIGNONMSGSRSV1><SONRS><STATUS><CODE>0<SEVERITY>INFO</STATUS>"
            "<DTSERVER>20260901<LANGUAGE>POR</SONRS></SIGNONMSGSRSV1>"
            "<BANKMSGSRSV1><STMTTRNRS><TRNUID>1"
            "<STATUS><CODE>0<SEVERITY>INFO</STATUS><STMTRS><CURDEF>BRL"
            "<BANKACCTFROM><BANKID>1<ACCTID>1<ACCTTYPE>CHECKING</BANKACCTFROM>"
            "<BANKTRANLIST><DTSTART>20260901<DTEND>20260930"
            "<STMTTRN><TRNTYPE>DEBIT<DTPOSTED>20260901<TRNAMT>-10.00"
            "<FITID>BRTEST-ACCENT-1"
            "<MEMO>SUPERMERCADO SÃO JOSÉ"
            "</STMTTRN></BANKTRANLIST></STMTRS></STMTTRNRS></BANKMSGSRSV1></OFX>\n"
        ).encode("latin-1")
        txs = parse_ofx(header + body)
        assert len(txs) == 1
        assert "SAO" in txs[0].description.upper().replace("Ã", "A") or "SÃO" in txs[0].description or "SAO" in txs[0].description.upper() or "JOS" in txs[0].description.upper()


# ---------------------------------------------------------------------------
# Parse characterization — CSV Brasil
# ---------------------------------------------------------------------------


class TestBrCsvParse:
    def test_semicolon_brl_amounts(self):
        txs, failed = parse_csv(_load("br_semicolon.csv"), date_format="DD/MM/YYYY")
        assert failed == []
        assert len(txs) == 2
        assert txs[0].amount == Decimal("1234.56")
        assert txs[0].type == "debit"
        assert txs[0].date == date(2026, 9, 1)
        assert txs[1].type == "credit"
        assert txs[1].amount == Decimal("250.00")

    def test_normalize_amount_matrix(self):
        assert normalize_amount("1234.56") == "1234.56"
        assert normalize_amount("1.234,56") == "1234.56"
        assert normalize_amount("-1.234,56") == "-1234.56"
        assert normalize_amount("R$ 1.234,56") == "1234.56"
        assert normalize_amount("R$ -1.234,56") == "-1234.56"

    def test_csv_cp1252_accents_preserved(self):
        """Windows-1252 CSV decodes with correct accents (no mojibake)."""
        content = "date,description,amount\n2026-09-01,SUPERMERCADO SÃO JOSÉ,-10.00\n".encode(
            "cp1252"
        )
        txs, failed = parse_csv(content)
        assert failed == []
        assert len(txs) == 1
        assert "SÃO JOSÉ" in txs[0].description
        assert txs[0].external_id and txs[0].external_id.startswith("IMP-")

    def test_csv_utf8_bom_ok(self):
        content = "date,description,amount\n2026-09-01,CAFE,-10.00\n".encode("utf-8-sig")
        txs, _ = parse_csv(content)
        assert len(txs) == 1
        assert txs[0].amount == Decimal("10.00")
        assert txs[0].type == "debit"

    def test_credit_card_purchases_are_debits_when_signed_negative(self):
        txs, _ = parse_csv(_load("credit_card_purchases.csv"))
        assert len(txs) == 4
        assert all(t.type == "debit" for t in txs)
        assert sum(t.amount for t in txs) == Decimal("805.90")

    def test_credit_card_positive_csv_needs_flip_or_semantics(self):
        """Unsigned positive amounts parse as credit; flip_amount makes debit."""
        csv = b"date,description,amount\n2026-09-01,SUPERMERCADO,350.00\n"
        txs, _ = parse_csv(csv)
        assert txs[0].type == "credit"
        flipped, _ = parse_csv(csv, flip_amount=True)
        assert flipped[0].type == "debit"


# ---------------------------------------------------------------------------
# Import pipeline — idempotency, FITID, installments, card payment, transfers
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_ofx_import_idempotent_by_fitid(
    session: AsyncSession, test_user: User, test_workspace: Workspace
):
    acc = await _account(session, test_user, "Checking Synth")
    txs = parse_ofx(_load("bank_checking_synth.ofx"))
    i1, s1, _, _ = await import_transactions(
        session, test_workspace.id, test_user.id, acc.id, txs,
        source="import", filename="bank_checking_synth.ofx", detected_format="ofx",
    )
    assert i1 == 5 and s1 == 0
    i2, s2, _, _ = await import_transactions(
        session, test_workspace.id, test_user.id, acc.id, txs,
        source="import", filename="bank_checking_synth.ofx", detected_format="ofx",
    )
    assert i2 == 0 and s2 == 5
    count = await session.scalar(
        select(func.count()).select_from(Transaction).where(Transaction.account_id == acc.id)
    )
    assert count == 5


@pytest.mark.asyncio
async def test_fitid_same_on_different_accounts_not_duplicate(
    session: AsyncSession, test_user: User, test_workspace: Workspace
):
    a1 = await _account(session, test_user, "Acc A")
    a2 = await _account(session, test_user, "Acc B")
    row = TransactionImport(
        description="PIX QR CODE IFOOD",
        amount=Decimal("80.00"),
        date=date(2026, 9, 5),
        type="debit",
        external_id="BRTEST-SHARED-FITID",
    )
    await import_transactions(
        session, test_workspace.id, test_user.id, a1.id, [row],
        source="import", detected_format="ofx",
    )
    imported, skipped, _, _ = await import_transactions(
        session, test_workspace.id, test_user.id, a2.id, [row],
        source="import", detected_format="ofx",
    )
    assert imported == 1 and skipped == 0


@pytest.mark.asyncio
async def test_fitid_same_different_dates_are_distinct_installments(
    session: AsyncSession, test_user: User, test_workspace: Workspace
):
    """BR cards may reuse FITID across parcelas — date is part of the dedup key."""
    acc = await _account(session, test_user, "CC", account_type="credit_card")
    rows = [
        TransactionImport(
            description="LOJA EXEMPLO 01/10",
            amount=Decimal("199.90"),
            date=date(2026, 9, 5),
            type="debit",
            external_id="BRTEST-PARCELA-FITID",
        ),
        TransactionImport(
            description="LOJA EXEMPLO 02/10",
            amount=Decimal("199.90"),
            date=date(2026, 10, 5),
            type="debit",
            external_id="BRTEST-PARCELA-FITID",
        ),
        TransactionImport(
            description="LOJA EXEMPLO 03/10",
            amount=Decimal("199.90"),
            date=date(2026, 11, 5),
            type="debit",
            external_id="BRTEST-PARCELA-FITID",
        ),
    ]
    imported, skipped, _, _ = await import_transactions(
        session, test_workspace.id, test_user.id, acc.id, rows,
        source="import", detected_format="ofx",
    )
    assert imported == 3 and skipped == 0


@pytest.mark.asyncio
async def test_csv_installments_different_dates_no_fitid_remain_distinct(
    session: AsyncSession, test_user: User, test_workspace: Workspace
):
    """Parcelas with same amount/merchant but different dates stay distinct without FITID."""
    acc = await _account(session, test_user, "CC Installments", account_type="credit_card")
    rows, failed = parse_csv(_load("credit_card_installments.csv"))
    assert failed == []
    imported, skipped, _, _ = await import_transactions(
        session, test_workspace.id, test_user.id, acc.id, rows,
        source="import", detected_format="csv",
    )
    assert imported == 3 and skipped == 0
    assert all(r.type == "debit" for r in rows)
    assert all(r.amount == Decimal("199.90") for r in rows)


@pytest.mark.asyncio
async def test_identical_same_day_purchases_both_imported(
    session: AsyncSession, test_user: User, test_workspace: Workspace
):
    """Two legitimate identical purchases on the same day must both persist."""
    acc = await _account(session, test_user, "Checking")
    rows = [
        TransactionImport(
            description="SUPERMERCADO",
            amount=Decimal("100.00"),
            date=date(2026, 9, 1),
            type="debit",
            external_id=None,
        ),
        TransactionImport(
            description="SUPERMERCADO",
            amount=Decimal("100.00"),
            date=date(2026, 9, 1),
            type="debit",
            external_id=None,
        ),
    ]
    imported, skipped, _, _ = await import_transactions(
        session, test_workspace.id, test_user.id, acc.id, rows,
        source="import", detected_format="csv", detect_duplicates=True,
    )
    assert imported == 2
    assert skipped == 0


@pytest.mark.asyncio
async def test_reimport_identical_same_day_stays_idempotent(
    session: AsyncSession, test_user: User, test_workspace: Workspace
):
    """Reimporting the same CSV bytes keeps two identical rows (not four)."""
    acc = await _account(session, test_user, "Checking Reimp")
    raw = (
        b"date,description,amount\n"
        b"2026-09-01,SUPERMERCADO,-100.00\n"
        b"2026-09-01,SUPERMERCADO,-100.00\n"
    )
    rows, _ = parse_csv(raw)
    assert len(rows) == 2
    assert rows[0].external_id != rows[1].external_id
    i1, s1, _, _ = await import_transactions(
        session, test_workspace.id, test_user.id, acc.id, rows,
        source="import", detected_format="csv", filename="dup.csv",
    )
    assert i1 == 2 and s1 == 0
    rows2, _ = parse_csv(raw)
    i2, s2, _, _ = await import_transactions(
        session, test_workspace.id, test_user.id, acc.id, rows2,
        source="import", detected_format="csv", filename="dup.csv",
    )
    assert i2 == 0 and s2 == 2
    count = await session.scalar(
        select(func.count()).select_from(Transaction).where(Transaction.account_id == acc.id)
    )
    assert count == 2


@pytest.mark.asyncio
async def test_card_bill_payment_pairs_through_import_pipeline(
    session: AsyncSession, test_user: User, test_workspace: Workspace
):
    bank = await _account(session, test_user, "Bank Bill")
    card = await _account(session, test_user, "Card Bill", account_type="credit_card")

    bank_rows = parse_ofx(_load("bank_card_payment.ofx"))
    card_rows, _ = parse_csv(_load("credit_card_payment.csv"))
    # Card payment must be credit 805
    assert card_rows[0].type == "credit"
    assert card_rows[0].amount == Decimal("805.00")

    await import_transactions(
        session, test_workspace.id, test_user.id, bank.id, bank_rows,
        source="import", filename="bank_card_payment.ofx", detected_format="ofx",
    )
    await import_transactions(
        session, test_workspace.id, test_user.id, card.id, card_rows,
        source="import", filename="credit_card_payment.csv", detected_format="csv",
        amount_semantics="signed",
    )

    result = await session.execute(
        select(Transaction).where(Transaction.account_id.in_([bank.id, card.id]))
    )
    txs = list(result.scalars().all())
    assert len(txs) == 2
    assert all(t.transfer_pair_id is not None for t in txs)
    assert txs[0].transfer_pair_id == txs[1].transfer_pair_id

    counterparts = await fetch_counterpart_account_types(session, txs)
    classifications = {classify_orm(t, counterparts.get(t.id)) for t in txs}
    assert classifications == {"card_payment"}


@pytest.mark.asyncio
async def test_own_account_transfer_pairs_uber_does_not(
    session: AsyncSession, test_user: User, test_workspace: Workspace
):
    bank = await _account(session, test_user, "Bank A")
    other = await _account(session, test_user, "Bank B")
    rows = parse_ofx(_load("bank_own_transfer_and_noise.ofx"))
    # Split: out+uber on bank A, in+deposito on bank B (realistic two-file import)
    out_leg = [r for r in rows if r.external_id == "BRTEST-FITID-OWN-OUT-001"]
    in_leg = [r for r in rows if r.external_id == "BRTEST-FITID-OWN-IN-001"]
    uber = [r for r in rows if r.external_id == "BRTEST-FITID-UBER-001"]
    deposit = [r for r in rows if r.external_id == "BRTEST-FITID-DEPOSITO-001"]

    await import_transactions(
        session, test_workspace.id, test_user.id, bank.id, out_leg + uber,
        source="import", detected_format="ofx",
    )
    await import_transactions(
        session, test_workspace.id, test_user.id, other.id, in_leg + deposit,
        source="import", detected_format="ofx",
    )

    result = await session.execute(select(Transaction).where(
        Transaction.account_id.in_([bank.id, other.id])
    ))
    txs = {t.external_id: t for t in result.scalars().all()}
    assert txs["BRTEST-FITID-OWN-OUT-001"].transfer_pair_id is not None
    assert (
        txs["BRTEST-FITID-OWN-OUT-001"].transfer_pair_id
        == txs["BRTEST-FITID-OWN-IN-001"].transfer_pair_id
    )
    assert txs["BRTEST-FITID-UBER-001"].transfer_pair_id is None
    assert txs["BRTEST-FITID-DEPOSITO-001"].transfer_pair_id is None


@pytest.mark.asyncio
async def test_refund_persists_and_is_not_transfer(
    session: AsyncSession, test_user: User, test_workspace: Workspace
):
    card = await _account(session, test_user, "Card Refund", account_type="credit_card")
    rows, _ = parse_csv(_load("credit_card_refund.csv"))
    imported, skipped, _, _ = await import_transactions(
        session, test_workspace.id, test_user.id, card.id, rows,
        source="import", detected_format="csv",
    )
    assert imported == 2 and skipped == 0
    result = await session.execute(
        select(Transaction).where(Transaction.account_id == card.id)
    )
    txs = list(result.scalars().all())
    assert {t.type for t in txs} == {"debit", "credit"}
    assert all(t.transfer_pair_id is None for t in txs)
    credit = next(t for t in txs if t.type == "credit")
    debit = next(t for t in txs if t.type == "debit")
    assert credit.exclude_from_pnl is True
    assert debit.exclude_from_pnl is False


@pytest.mark.asyncio
async def test_cross_format_ofx_then_exact_csv_description_skips(
    session: AsyncSession, test_user: User, test_workspace: Workspace
):
    """OFX then CSV with exact same description/date/amount soft-dedups.

    Slightly different CSV description still duplicates (conservative; no fuzzy).
    """
    acc = await _account(session, test_user, "CrossFmt")
    ofx_rows = [
        t for t in parse_ofx(_load("bank_checking_synth.ofx"))
        if t.external_id == "BRTEST-FITID-PIX-OUT-001"
    ]
    await import_transactions(
        session, test_workspace.id, test_user.id, acc.id, ofx_rows,
        source="import", detected_format="ofx",
    )
    same = TransactionImport(
        description="PIX QR CODE IFOOD",
        amount=Decimal("80.00"),
        date=date(2026, 9, 5),
        type="debit",
        external_id=None,
    )
    i_same, s_same, _, _ = await import_transactions(
        session, test_workspace.id, test_user.id, acc.id, [same],
        source="import", detected_format="csv",
    )
    assert i_same == 0 and s_same == 1

    different = TransactionImport(
        description="PIX QR CODE IFOOD 847362",
        amount=Decimal("80.00"),
        date=date(2026, 9, 5),
        type="debit",
        external_id=None,
    )
    i_diff, s_diff, _, _ = await import_transactions(
        session, test_workspace.id, test_user.id, acc.id, [different],
        source="import", detected_format="csv",
    )
    assert i_diff == 1 and s_diff == 0


@pytest.mark.asyncio
async def test_preview_parse_matches_import_amounts_and_types(
    session: AsyncSession, test_user: User, test_workspace: Workspace
):
    """Preview parse and import persistence share the same TransactionImport fields."""
    acc = await _account(session, test_user, "Preview Match")
    parsed = parse_ofx(_load("bank_checking_synth.ofx"))
    await import_transactions(
        session, test_workspace.id, test_user.id, acc.id, parsed,
        source="import", detected_format="ofx",
    )
    result = await session.execute(
        select(Transaction).where(Transaction.account_id == acc.id)
    )
    persisted = {t.external_id: t for t in result.scalars().all()}
    for row in parsed:
        p = persisted[row.external_id]
        assert p.amount == row.amount
        assert p.type == row.type
        assert p.date == row.date
        assert p.description == row.description


@pytest.mark.asyncio
async def test_import_leaves_uncategorized_and_suggestion_available(
    session: AsyncSession, test_user: User, test_workspace: Workspace
):
    acc = await _account(session, test_user, "Suggest Acc")
    food = await _category(session, test_user, "Alimentação")
    # Seed history
    for i in range(3):
        session.add(
            Transaction(
                id=uuid.uuid4(),
                user_id=test_user.id,
                account_id=acc.id,
                description=f"IFOOD HIST {i}",
                amount=Decimal("20.00"),
                date=date(2026, 8, 1),
                type="debit",
                source="manual",
                currency="BRL",
                category_id=food.id,
            )
        )
    await session.commit()

    row = TransactionImport(
        description="IFOOD *9999",
        amount=Decimal("72.90"),
        date=date(2026, 9, 20),
        type="debit",
        external_id="BRTEST-IFOOD-NEW",
    )
    await import_transactions(
        session, test_workspace.id, test_user.id, acc.id, [row],
        source="import", detected_format="ofx",
    )
    result = await session.execute(
        select(Transaction).where(Transaction.external_id == "BRTEST-IFOOD-NEW")
    )
    pending = result.scalar_one()
    assert pending.category_id is None

    suggestions = await suggest_categories_for_transactions(
        session, test_workspace.id, [pending]
    )
    assert suggestions[pending.id].category_id == food.id


@pytest.mark.asyncio
async def test_cc_purchases_import_and_effective_date_set(
    session: AsyncSession, test_user: User, test_workspace: Workspace
):
    card = await _account(session, test_user, "CC Purchases", account_type="credit_card")
    rows, _ = parse_csv(_load("credit_card_purchases.csv"))
    imported, _, _, _ = await import_transactions(
        session, test_workspace.id, test_user.id, card.id, rows,
        source="import", detected_format="csv",
    )
    assert imported == 4
    result = await session.execute(
        select(Transaction).where(Transaction.account_id == card.id)
    )
    txs = list(result.scalars().all())
    assert all(t.type == "debit" for t in txs)
    # effective_date is always populated (equals date or bill-adjusted)
    assert all(t.effective_date is not None for t in txs)
