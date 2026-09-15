"""P0 financial integrity scenarios for Brazilian personal finance.

Epic 1: transfer detection after file import, card-payment pairing,
Pix-as-payment (not auto-transfer), and OFX idempotency.

These tests encode the expected post-fix behaviour. Before the
implementation they document current gaps (failed auto-pair after import,
over-aggressive Pix→Transfers rules, false-positive amount-only pairing).
"""
from __future__ import annotations

import uuid
from datetime import date, datetime, timezone
from decimal import Decimal

import pytest
from sqlalchemy import case, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.account import Account
from app.models.category import Category
from app.models.transaction import Transaction
from app.schemas.transaction import TransactionImport
from app.services._query_filters import counts_as_pnl
from app.services.category_service import create_default_categories
from app.services.import_service import import_transactions
from app.services.rule_service import (
    RULE_PACKS,
    apply_rules_to_transaction,
    install_rule_pack,
)
from app.services.transfer_detection_service import detect_transfer_pairs


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


async def _make_account(
    session: AsyncSession,
    user_id: uuid.UUID,
    name: str,
    *,
    account_type: str = "checking",
) -> Account:
    account = Account(
        id=uuid.uuid4(),
        user_id=user_id,
        name=name,
        type=account_type,
        balance=Decimal("0.00"),
        currency="BRL",
    )
    session.add(account)
    await session.commit()
    await session.refresh(account)
    return account


async def _import_one(
    session: AsyncSession,
    workspace_id: uuid.UUID,
    user_id: uuid.UUID,
    account_id: uuid.UUID,
    *,
    description: str,
    amount: Decimal,
    txn_type: str,
    txn_date: date,
    external_id: str | None = None,
    source: str = "ofx",
    amount_semantics: str | None = None,
) -> tuple[int, int, list[Transaction]]:
    txn = TransactionImport(
        description=description,
        amount=amount,
        date=txn_date,
        type=txn_type,
        external_id=external_id,
        currency="BRL",
    )
    imported, skipped, _, _ = await import_transactions(
        session,
        workspace_id,
        user_id,
        account_id,
        [txn],
        source,
        filename=f"{description}.ofx",
        detected_format=source,
        amount_semantics=amount_semantics,
    )
    result = await session.execute(
        select(Transaction).where(
            Transaction.account_id == account_id,
            Transaction.description == description,
            Transaction.date == txn_date,
            Transaction.amount == amount,
        )
    )
    return imported, skipped, list(result.scalars().all())


async def _pnl_totals(
    session: AsyncSession, workspace_id: uuid.UUID
) -> tuple[Decimal, Decimal]:
    amount_expr = func.coalesce(Transaction.amount_primary, Transaction.amount)
    row = (
        await session.execute(
            select(
                func.coalesce(
                    func.sum(case((Transaction.type == "credit", amount_expr), else_=0)),
                    0,
                ),
                func.coalesce(
                    func.sum(case((Transaction.type == "debit", amount_expr), else_=0)),
                    0,
                ),
            ).where(
                Transaction.workspace_id == workspace_id,
                counts_as_pnl(),
            )
        )
    ).one()
    return Decimal(str(row[0])), Decimal(str(row[1]))


def _assert_not_treat_as_transfer(category: Category | None) -> None:
    if category is None:
        return
    assert category.treat_as_transfer is not True


# ---------------------------------------------------------------------------
# Scenario A — own-account transfer via file import
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_scenario_a_pix_transfer_paired_after_import_and_excluded_from_pnl(
    session: AsyncSession, test_user, test_workspace
):
    """Itaú PIX out + Nubank PIX in → same transfer_pair_id, zero P&L."""
    itau = await _make_account(session, test_user.id, "Itaú")
    nubank = await _make_account(session, test_user.id, "Nubank")
    today = date.today()

    imported_a, _, txs_a = await _import_one(
        session,
        test_workspace.id,
        test_user.id,
        itau.id,
        description="PIX ENVIADO",
        amount=Decimal("1000.00"),
        txn_type="debit",
        txn_date=today,
        external_id="FITID-A-1000",
    )
    imported_b, _, txs_b = await _import_one(
        session,
        test_workspace.id,
        test_user.id,
        nubank.id,
        description="PIX RECEBIDO",
        amount=Decimal("1000.00"),
        txn_type="credit",
        txn_date=today,
        external_id="FITID-B-1000",
    )

    assert imported_a == 1 and imported_b == 1
    assert len(txs_a) == 1 and len(txs_b) == 1
    debit, credit = txs_a[0], txs_b[0]

    assert debit.transfer_pair_id is not None
    assert debit.transfer_pair_id == credit.transfer_pair_id

    income, expenses = await _pnl_totals(session, test_workspace.id)
    assert income == Decimal("0")
    assert expenses == Decimal("0")


@pytest.mark.asyncio
async def test_scenario_a_sequential_import_pairs_when_second_leg_arrives(
    session: AsyncSession, test_user, test_workspace
):
    """candidate_ids means at least one new leg — second OFX must still pair."""
    itau = await _make_account(session, test_user.id, "Itaú Seq")
    nubank = await _make_account(session, test_user.id, "Nubank Seq")
    today = date.today()

    await _import_one(
        session,
        test_workspace.id,
        test_user.id,
        itau.id,
        description="PIX ENVIADO NUBANK",
        amount=Decimal("250.00"),
        txn_type="debit",
        txn_date=today,
        external_id="FITID-SEQ-OUT",
    )
    # First leg alone must not invent a pair.
    first = (
        await session.execute(
            select(Transaction).where(Transaction.external_id == "FITID-SEQ-OUT")
        )
    ).scalar_one()
    assert first.transfer_pair_id is None

    await _import_one(
        session,
        test_workspace.id,
        test_user.id,
        nubank.id,
        description="PIX RECEBIDO ITAU",
        amount=Decimal("250.00"),
        txn_type="credit",
        txn_date=today,
        external_id="FITID-SEQ-IN",
    )

    await session.refresh(first)
    second = (
        await session.execute(
            select(Transaction).where(Transaction.external_id == "FITID-SEQ-IN")
        )
    ).scalar_one()
    assert first.transfer_pair_id is not None
    assert first.transfer_pair_id == second.transfer_pair_id


# ---------------------------------------------------------------------------
# Scenario B — credit-card bill payment
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_scenario_b_card_payment_paired_expenses_equal_purchases_only(
    session: AsyncSession, test_user, test_workspace
):
    """Purchases R$805 + bill payment legs → P&L expenses == 805, not 1610."""
    bank = await _make_account(session, test_user.id, "Itaú CC Pay")
    card = await _make_account(
        session, test_user.id, "Cartão", account_type="credit_card"
    )
    today = date.today()

    purchases = [
        ("Supermercado", Decimal("350.00")),
        ("Combustível", Decimal("280.00")),
        ("Restaurante", Decimal("120.00")),
        ("Netflix", Decimal("55.00")),
    ]
    for i, (desc, amount) in enumerate(purchases):
        imported, _, _ = await _import_one(
            session,
            test_workspace.id,
            test_user.id,
            card.id,
            description=desc,
            amount=amount,
            txn_type="debit",
            txn_date=today,
            external_id=f"CC-PURCHASE-{i}",
        )
        assert imported == 1

    await _import_one(
        session,
        test_workspace.id,
        test_user.id,
        bank.id,
        description="PAGAMENTO CARTAO",
        amount=Decimal("805.00"),
        txn_type="debit",
        txn_date=today,
        external_id="BANK-CC-PAY",
    )
    await _import_one(
        session,
        test_workspace.id,
        test_user.id,
        card.id,
        description="PAGAMENTO FATURA",
        amount=Decimal("805.00"),
        txn_type="credit",
        txn_date=today,
        external_id="CC-BILL-CREDIT",
        amount_semantics="signed",
    )

    pay_debit = (
        await session.execute(
            select(Transaction).where(Transaction.external_id == "BANK-CC-PAY")
        )
    ).scalar_one()
    pay_credit = (
        await session.execute(
            select(Transaction).where(Transaction.external_id == "CC-BILL-CREDIT")
        )
    ).scalar_one()
    assert pay_debit.transfer_pair_id is not None
    assert pay_debit.transfer_pair_id == pay_credit.transfer_pair_id

    income, expenses = await _pnl_totals(session, test_workspace.id)
    assert income == Decimal("0")
    assert expenses == Decimal("805.00")


# ---------------------------------------------------------------------------
# Scenario C — false positive (critical)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_scenario_c_same_amount_unrelated_must_not_auto_pair(
    session: AsyncSession, test_user, test_workspace
):
    """UBER debit + client deposit credit must NOT pair on amount/date alone."""
    acc_a = await _make_account(session, test_user.id, "Conta A")
    acc_b = await _make_account(session, test_user.id, "Conta B")
    today = date.today()

    await _import_one(
        session,
        test_workspace.id,
        test_user.id,
        acc_a.id,
        description="UBER",
        amount=Decimal("100.00"),
        txn_type="debit",
        txn_date=today,
        external_id="UBER-100",
    )
    await _import_one(
        session,
        test_workspace.id,
        test_user.id,
        acc_b.id,
        description="DEPOSITO CLIENTE",
        amount=Decimal("100.00"),
        txn_type="credit",
        txn_date=today,
        external_id="DEP-100",
    )

    debit = (
        await session.execute(
            select(Transaction).where(Transaction.external_id == "UBER-100")
        )
    ).scalar_one()
    credit = (
        await session.execute(
            select(Transaction).where(Transaction.external_id == "DEP-100")
        )
    ).scalar_one()
    assert debit.transfer_pair_id is None
    assert credit.transfer_pair_id is None

    income, expenses = await _pnl_totals(session, test_workspace.id)
    assert expenses == Decimal("100.00")
    assert income == Decimal("100.00")


@pytest.mark.asyncio
async def test_scenario_c_ambiguous_equal_candidates_do_not_auto_pair(
    session: AsyncSession, test_user, test_workspace
):
    """Two equally plausible PIX credits → no auto-pair."""
    from_acc = await _make_account(session, test_user.id, "Origem Amb")
    to_a = await _make_account(session, test_user.id, "Dest A Amb")
    to_b = await _make_account(session, test_user.id, "Dest B Amb")
    today = date.today()

    debit = Transaction(
        id=uuid.uuid4(),
        user_id=test_user.id,
        account_id=from_acc.id,
        description="PIX ENVIADO",
        amount=Decimal("100.00"),
        date=today,
        type="debit",
        source="ofx",
        currency="BRL",
        created_at=datetime.now(timezone.utc),
    )
    credit_a = Transaction(
        id=uuid.uuid4(),
        user_id=test_user.id,
        account_id=to_a.id,
        description="PIX RECEBIDO",
        amount=Decimal("100.00"),
        date=today,
        type="credit",
        source="ofx",
        currency="BRL",
        created_at=datetime.now(timezone.utc),
    )
    credit_b = Transaction(
        id=uuid.uuid4(),
        user_id=test_user.id,
        account_id=to_b.id,
        description="PIX RECEBIDO",
        amount=Decimal("100.00"),
        date=today,
        type="credit",
        source="ofx",
        currency="BRL",
        created_at=datetime.now(timezone.utc),
    )
    session.add_all([debit, credit_a, credit_b])
    await session.commit()

    pairs = await detect_transfer_pairs(
        session, test_workspace.id, candidate_ids=[debit.id, credit_a.id, credit_b.id]
    )
    await session.commit()
    assert pairs == 0

    await session.refresh(debit)
    await session.refresh(credit_a)
    await session.refresh(credit_b)
    assert debit.transfer_pair_id is None
    assert credit_a.transfer_pair_id is None
    assert credit_b.transfer_pair_id is None


# ---------------------------------------------------------------------------
# Scenario D — PIX payment to merchant stays expense
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_scenario_d_pix_qr_ifood_remains_expense_not_transfer_category(
    session: AsyncSession, test_user, test_workspace
):
    await create_default_categories(session, test_user.id, lang="pt-BR")
    await install_rule_pack(session, test_workspace.id, test_user.id, "BR", lang="pt-BR")

    account = await _make_account(session, test_user.id, "Conta IFood")
    today = date.today()

    imported, _, txs = await _import_one(
        session,
        test_workspace.id,
        test_user.id,
        account.id,
        description="PIX QR CODE IFOOD",
        amount=Decimal("80.00"),
        txn_type="debit",
        txn_date=today,
        external_id="PIX-IFOOD-80",
    )
    assert imported == 1
    tx = txs[0]
    await session.refresh(tx, ["category"])

    _assert_not_treat_as_transfer(tx.category)
    if tx.category is not None:
        assert tx.category.treat_as_transfer is False

    income, expenses = await _pnl_totals(session, test_workspace.id)
    assert expenses == Decimal("80.00")
    assert income == Decimal("0")


# ---------------------------------------------------------------------------
# Scenario E — PIX to third party must stay in P&L without counterpart
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_scenario_e_pix_enviado_to_third_party_stays_in_pnl(
    session: AsyncSession, test_user, test_workspace
):
    await create_default_categories(session, test_user.id, lang="pt-BR")
    await install_rule_pack(session, test_workspace.id, test_user.id, "BR", lang="pt-BR")

    account = await _make_account(session, test_user.id, "Conta Pix Terceiro")
    today = date.today()

    imported, _, txs = await _import_one(
        session,
        test_workspace.id,
        test_user.id,
        account.id,
        description="PIX ENVIADO JOAO SILVA",
        amount=Decimal("500.00"),
        txn_type="debit",
        txn_date=today,
        external_id="PIX-JOAO-500",
    )
    assert imported == 1
    tx = txs[0]
    await session.refresh(tx, ["category"])

    assert tx.transfer_pair_id is None
    _assert_not_treat_as_transfer(tx.category)

    income, expenses = await _pnl_totals(session, test_workspace.id)
    assert expenses == Decimal("500.00")


@pytest.mark.asyncio
async def test_br_pack_has_no_generic_pix_to_transfers_rules():
    """RULE_PACKS['BR'] must not auto-map generic PIX/TRANSFERENCIA to Transfers."""
    rules = RULE_PACKS["BR"]["rules"]
    names = {r["name"] for r in rules}
    assert "Pix Enviado" not in names
    assert "Pix Recebido" not in names
    assert "Transferência" not in names

    for rule in rules:
        for condition in rule.get("conditions", []):
            value = str(condition.get("value", "")).upper()
            if "PIX" in value and any(
                token in value for token in ("ENVIADO", "RECEBIDO", "TRANSF")
            ):
                actions = rule.get("actions", [])
                assert not any(
                    a.get("op") == "set_category" and a.get("value") == "transfers"
                    for a in actions
                ), f"Dangerous generic PIX→transfers rule still present: {rule['name']}"
            if "TRANSFERENCIA" in value:
                actions = rule.get("actions", [])
                assert not any(
                    a.get("op") == "set_category" and a.get("value") == "transfers"
                    for a in actions
                ), f"Dangerous TRANSFERENCIA→transfers rule still present: {rule['name']}"


@pytest.mark.asyncio
async def test_br_pack_still_has_merchant_rules():
    names = {r["name"] for r in RULE_PACKS["BR"]["rules"]}
    assert "iFood / Rappi" in names
    assert "99 (Ride-hailing)" in names
    assert "Mercado Livre" in names


# ---------------------------------------------------------------------------
# Scenario F — OFX import idempotency
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_scenario_f_ofx_reimport_is_idempotent(
    session: AsyncSession, test_user, test_workspace
):
    account = await _make_account(session, test_user.id, "Conta Idempotente")
    today = date.today()
    payload = [
        TransactionImport(
            description="COMPRA MERCADO",
            amount=Decimal("42.50"),
            date=today,
            type="debit",
            external_id="FITID-IDEMP-1",
            currency="BRL",
        )
    ]

    imported1, skipped1, _, _ = await import_transactions(
        session,
        test_workspace.id,
        test_user.id,
        account.id,
        payload,
        "ofx",
        filename="stmt.ofx",
        detected_format="ofx",
    )
    imported2, skipped2, _, _ = await import_transactions(
        session,
        test_workspace.id,
        test_user.id,
        account.id,
        payload,
        "ofx",
        filename="stmt.ofx",
        detected_format="ofx",
    )

    assert imported1 > 0
    assert skipped1 == 0
    assert imported2 == 0
    assert skipped2 > 0

    count = (
        await session.execute(
            select(func.count())
            .select_from(Transaction)
            .where(
                Transaction.account_id == account.id,
                Transaction.external_id == "FITID-IDEMP-1",
            )
        )
    ).scalar_one()
    assert count == 1


# ---------------------------------------------------------------------------
# Detector money type: Decimal keys (no float)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_detector_pairs_decimal_amounts_without_float_keys(
    session: AsyncSession, test_user, test_workspace
):
    """Amounts like 10.10 must match via Decimal, not float buckets."""
    a = await _make_account(session, test_user.id, "Dec A")
    b = await _make_account(session, test_user.id, "Dec B")
    today = date.today()

    debit = Transaction(
        id=uuid.uuid4(),
        user_id=test_user.id,
        account_id=a.id,
        description="PIX ENVIADO",
        amount=Decimal("10.10"),
        date=today,
        type="debit",
        source="ofx",
        currency="BRL",
        created_at=datetime.now(timezone.utc),
    )
    credit = Transaction(
        id=uuid.uuid4(),
        user_id=test_user.id,
        account_id=b.id,
        description="PIX RECEBIDO",
        amount=Decimal("10.10"),
        date=today,
        type="credit",
        source="ofx",
        currency="BRL",
        created_at=datetime.now(timezone.utc),
    )
    session.add_all([debit, credit])
    await session.commit()

    pairs = await detect_transfer_pairs(session, test_workspace.id)
    await session.commit()
    assert pairs == 1
    await session.refresh(debit)
    await session.refresh(credit)
    assert debit.transfer_pair_id == credit.transfer_pair_id
