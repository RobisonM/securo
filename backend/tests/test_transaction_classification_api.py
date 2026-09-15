"""API contract tests for derived transaction ``classification`` (Epic 2B)."""

from __future__ import annotations

import uuid
from datetime import date, datetime, timezone
from decimal import Decimal

import pytest
from httpx import AsyncClient
from sqlalchemy import event
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.account import Account
from app.models.category import Category
from app.models.transaction import Transaction
from app.services.category_service import create_default_categories
from app.services.rule_service import RULE_PACKS, apply_rules_to_transaction, install_rule_pack
from app.services.transaction_service import (
    build_transaction_reads,
    fetch_counterpart_account_types,
)


async def _account(
    session: AsyncSession, user, name: str, *, account_type: str = "checking"
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


async def _category(
    session: AsyncSession, user, name: str, *, treat_as_transfer: bool = False
) -> Category:
    cat = Category(
        id=uuid.uuid4(),
        user_id=user.id,
        name=name,
        icon="circle",
        color="#000000",
        treat_as_transfer=treat_as_transfer,
    )
    session.add(cat)
    await session.commit()
    await session.refresh(cat)
    return cat


async def _tx(
    session: AsyncSession,
    user,
    account: Account,
    *,
    description: str,
    amount: Decimal,
    txn_type: str,
    category: Category | None = None,
    transfer_pair_id: uuid.UUID | None = None,
    exclude_from_pnl: bool = False,
) -> Transaction:
    tx = Transaction(
        id=uuid.uuid4(),
        user_id=user.id,
        account_id=account.id,
        description=description,
        amount=amount,
        date=date.today(),
        type=txn_type,
        source="manual",
        currency="BRL",
        category_id=category.id if category else None,
        transfer_pair_id=transfer_pair_id,
        exclude_from_pnl=exclude_from_pnl,
        created_at=datetime.now(timezone.utc),
    )
    session.add(tx)
    await session.commit()
    return tx


@pytest.mark.asyncio
async def test_list_exposes_all_classifications(
    client: AsyncClient, auth_headers, session: AsyncSession, test_user, test_workspace
):
    """Acceptance mix: salary, grocery, transfer, card payment, adjustment, uncertain."""
    bank = await _account(session, test_user, "Itaú")
    savings = await _account(session, test_user, "Nubank Poupança", account_type="savings")
    card = await _account(session, test_user, "Cartão", account_type="credit_card")
    income_cat = await _category(session, test_user, "Salário")
    expense_cat = await _category(session, test_user, "Mercado")

    await _tx(
        session, test_user, bank,
        description="SALARIO", amount=Decimal("5000"), txn_type="credit", category=income_cat,
    )
    await _tx(
        session, test_user, bank,
        description="SUPERMERCADO", amount=Decimal("120"), txn_type="debit", category=expense_cat,
    )
    pair_xfer = uuid.uuid4()
    await _tx(
        session, test_user, bank,
        description="PIX ENVIADO NUBANK", amount=Decimal("200"), txn_type="debit",
        transfer_pair_id=pair_xfer,
    )
    await _tx(
        session, test_user, savings,
        description="PIX RECEBIDO ITAU", amount=Decimal("200"), txn_type="credit",
        transfer_pair_id=pair_xfer,
    )
    pair_card = uuid.uuid4()
    await _tx(
        session, test_user, bank,
        description="PAGAMENTO CARTAO", amount=Decimal("805"), txn_type="debit",
        transfer_pair_id=pair_card,
    )
    await _tx(
        session, test_user, card,
        description="PAGAMENTO FATURA", amount=Decimal("805"), txn_type="credit",
        transfer_pair_id=pair_card,
    )
    await _tx(
        session, test_user, bank,
        description="AJUSTE SALDO", amount=Decimal("10"), txn_type="debit",
        exclude_from_pnl=True,
    )
    await _tx(
        session, test_user, bank,
        description="SEM CATEGORIA", amount=Decimal("33"), txn_type="debit",
    )

    resp = await client.get("/api/transactions?limit=100", headers=auth_headers)
    assert resp.status_code == 200
    by_desc = {t["description"]: t["classification"] for t in resp.json()["items"]}
    assert by_desc["SALARIO"] == "income"
    assert by_desc["SUPERMERCADO"] == "expense"
    assert by_desc["PIX ENVIADO NUBANK"] == "transfer"
    assert by_desc["PIX RECEBIDO ITAU"] == "transfer"
    assert by_desc["PAGAMENTO CARTAO"] == "card_payment"
    assert by_desc["PAGAMENTO FATURA"] == "card_payment"
    assert by_desc["AJUSTE SALDO"] == "adjustment"
    assert by_desc["SEM CATEGORIA"] == "uncertain"


@pytest.mark.asyncio
async def test_get_transaction_classification_income(
    client: AsyncClient, auth_headers, session: AsyncSession, test_user
):
    bank = await _account(session, test_user, "Conta Income")
    cat = await _category(session, test_user, "Receita")
    tx = await _tx(
        session, test_user, bank,
        description="FREELA", amount=Decimal("1000"), txn_type="credit", category=cat,
    )
    resp = await client.get(f"/api/transactions/{tx.id}", headers=auth_headers)
    assert resp.status_code == 200
    assert resp.json()["classification"] == "income"


@pytest.mark.asyncio
async def test_treat_as_transfer_unilateral_via_api(
    client: AsyncClient, auth_headers, session: AsyncSession, test_user
):
    bank = await _account(session, test_user, "Conta Invest")
    cat = await _category(session, test_user, "Investimentos", treat_as_transfer=True)
    tx = await _tx(
        session, test_user, bank,
        description="APLICACAO", amount=Decimal("500"), txn_type="debit", category=cat,
    )
    resp = await client.get(f"/api/transactions/{tx.id}", headers=auth_headers)
    assert resp.json()["classification"] == "transfer"


@pytest.mark.asyncio
async def test_uncategorized_excludes_pairs_and_adjustments(
    client: AsyncClient, auth_headers, session: AsyncSession, test_user
):
    bank = await _account(session, test_user, "Conta Pend")
    other = await _account(session, test_user, "Conta Pend 2")
    pending = await _tx(
        session, test_user, bank,
        description="PENDENTE", amount=Decimal("40"), txn_type="debit",
    )
    pair = uuid.uuid4()
    await _tx(
        session, test_user, bank,
        description="XFER OUT", amount=Decimal("40"), txn_type="debit",
        transfer_pair_id=pair,
    )
    await _tx(
        session, test_user, other,
        description="XFER IN", amount=Decimal("40"), txn_type="credit",
        transfer_pair_id=pair,
    )
    await _tx(
        session, test_user, bank,
        description="AJUSTE", amount=Decimal("5"), txn_type="debit",
        exclude_from_pnl=True,
    )

    resp = await client.get("/api/transactions?uncategorized=true", headers=auth_headers)
    assert resp.status_code == 200
    items = resp.json()["items"]
    descs = {t["description"] for t in items}
    assert "PENDENTE" in descs
    assert "XFER OUT" not in descs
    assert "XFER IN" not in descs
    assert "AJUSTE" not in descs
    assert all(t["category_id"] is None for t in items)
    assert all(t["classification"] == "uncertain" for t in items)
    assert pending.id  # silence unused if filtered


@pytest.mark.asyncio
async def test_counterpart_fetch_is_single_extra_query(
    session: AsyncSession, test_user
):
    """Paired list enrichment uses one batch query, not one per transaction."""
    bank = await _account(session, test_user, "Q Bank")
    savings = await _account(session, test_user, "Q Sav", account_type="savings")
    card = await _account(session, test_user, "Q Card", account_type="credit_card")

    txs: list[Transaction] = []
    for i in range(10):
        pair = uuid.uuid4()
        d = await _tx(
            session, test_user, bank,
            description=f"OUT {i}", amount=Decimal("10"), txn_type="debit",
            transfer_pair_id=pair,
        )
        c = await _tx(
            session, test_user, savings if i % 2 == 0 else card,
            description=f"IN {i}", amount=Decimal("10"), txn_type="credit",
            transfer_pair_id=pair,
        )
        txs.extend([d, c])

    # Reload with relationships as list endpoint would
    from sqlalchemy import select
    from sqlalchemy.orm import selectinload

    result = await session.execute(
        select(Transaction)
        .where(Transaction.id.in_([t.id for t in txs]))
        .options(
            selectinload(Transaction.account),
            selectinload(Transaction.category),
            selectinload(Transaction.splits),
            selectinload(Transaction.payee_entity),
        )
    )
    loaded = list(result.scalars().unique().all())

    sync_conn = await session.connection()
    sync_engine = sync_conn.sync_connection.engine
    statements: list[str] = []

    def _count(conn, cursor, statement, parameters, context, executemany):
        statements.append(statement)

    event.listen(sync_engine, "before_cursor_execute", _count)
    try:
        counterparts = await fetch_counterpart_account_types(session, loaded)
        reads = await build_transaction_reads(session, loaded, "BRL")
    finally:
        event.remove(sync_engine, "before_cursor_execute", _count)

    assert len(counterparts) == len(loaded)
    assert all(r.classification in {"transfer", "card_payment"} for r in reads)
    # One SELECT for counterparts inside fetch; build_transaction_reads reuses
    # that path once — total counterpart-related queries must stay O(1).
    counterpart_selects = [
        s for s in statements
        if "transfer_pair_id" in s.lower() or "FROM transactions" in s.lower()
    ]
    assert len(statements) <= 2, f"expected O(1) queries, got {len(statements)}: {statements}"


@pytest.mark.asyncio
async def test_br_pack_no_generic_transferencia_or_pix_auto_transfer(
    session: AsyncSession, test_user, test_workspace
):
    names = {r["name"] for r in RULE_PACKS["BR"]["rules"]}
    assert "Transferência" not in names
    assert "Pix Enviado" not in names
    assert "Pix Recebido" not in names

    await create_default_categories(session, test_user.id, lang="pt-BR")
    await install_rule_pack(session, test_workspace.id, test_user.id, "BR", lang="pt-BR")

    bank = await _account(session, test_user, "Pack Bank")
    for description in (
        "PIX ENVIADO JOAO SILVA",
        "PIX RECEBIDO MARIA",
        "TRANSFERENCIA PAGAMENTO FORNECEDOR",
    ):
        tx = Transaction(
            id=uuid.uuid4(),
            user_id=test_user.id,
            account_id=bank.id,
            description=description,
            amount=Decimal("50"),
            date=date.today(),
            type="debit",
            source="ofx",
            currency="BRL",
            created_at=datetime.now(timezone.utc),
        )
        session.add(tx)
        await session.flush()
        await apply_rules_to_transaction(session, test_user.id, tx)
        await session.commit()
        await session.refresh(tx, ["category"])
        assert tx.category_id is None or (
            tx.category is not None and tx.category.treat_as_transfer is not True
        ), description

    # Merchants still resolve
    ifood = Transaction(
        id=uuid.uuid4(),
        user_id=test_user.id,
        account_id=bank.id,
        description="IFOOD RESTAURANTE",
        amount=Decimal("45"),
        date=date.today(),
        type="debit",
        source="ofx",
        currency="BRL",
        created_at=datetime.now(timezone.utc),
    )
    session.add(ifood)
    await session.flush()
    await apply_rules_to_transaction(session, test_user.id, ifood)
    await session.commit()
    await session.refresh(ifood, ["category"])
    assert ifood.category_id is not None
    assert ifood.category.treat_as_transfer is not True


@pytest.mark.asyncio
async def test_workspace_isolation_classification(
    client: AsyncClient, auth_headers, session: AsyncSession, test_user
):
    """Other workspace transactions must not appear in list/get."""
    from app.models.workspace import Workspace, WorkspaceMember

    other_ws = Workspace(
        id=uuid.uuid4(),
        name="Outro",
        kind="personal",
        created_by_user_id=test_user.id,
        default_currency="BRL",
        locale="pt-BR",
    )
    session.add(other_ws)
    await session.flush()
    session.add(
        WorkspaceMember(
            id=uuid.uuid4(),
            workspace_id=other_ws.id,
            user_id=test_user.id,
            role="owner",
        )
    )
    # Stamp account into other workspace explicitly
    acc = Account(
        id=uuid.uuid4(),
        user_id=test_user.id,
        workspace_id=other_ws.id,
        name="Outra Conta",
        type="checking",
        balance=Decimal("0"),
        currency="BRL",
    )
    session.add(acc)
    await session.flush()
    foreign = Transaction(
        id=uuid.uuid4(),
        user_id=test_user.id,
        workspace_id=other_ws.id,
        account_id=acc.id,
        description="FOREIGN TX",
        amount=Decimal("99"),
        date=date.today(),
        type="debit",
        source="manual",
        currency="BRL",
        created_at=datetime.now(timezone.utc),
    )
    session.add(foreign)
    await session.commit()

    resp = await client.get("/api/transactions?limit=200", headers=auth_headers)
    assert all(t["description"] != "FOREIGN TX" for t in resp.json()["items"])
    resp_get = await client.get(f"/api/transactions/{foreign.id}", headers=auth_headers)
    assert resp_get.status_code == 404
