"""Epic 3A — historical category suggestions (consensus, isolation, batch)."""

from __future__ import annotations

import uuid
from datetime import date
from decimal import Decimal

import pytest
from httpx import AsyncClient
from sqlalchemy import event
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.account import Account
from app.models.category import Category
from app.models.payee import Payee
from app.models.transaction import Transaction
from app.models.user import User
from app.models.workspace import Workspace, WorkspaceMember
from app.services.category_suggestion_service import (
    DOMINANT_RATIO,
    MIN_SAMPLES,
    suggest_categories_for_transactions,
)


async def _account(
    session: AsyncSession, user: User, name: str, *, account_type: str = "checking"
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
    session: AsyncSession,
    user: User,
    name: str,
    *,
    treat_as_transfer: bool = False,
    is_ignored: bool = False,
) -> Category:
    cat = Category(
        id=uuid.uuid4(),
        user_id=user.id,
        name=name,
        icon="circle",
        color="#000000",
        treat_as_transfer=treat_as_transfer,
        is_ignored=is_ignored,
    )
    session.add(cat)
    await session.commit()
    await session.refresh(cat)
    return cat


async def _payee(session: AsyncSession, user: User, name: str) -> Payee:
    p = Payee(
        id=uuid.uuid4(),
        user_id=user.id,
        name=name,
        type="company",
        source="manual",
    )
    session.add(p)
    await session.commit()
    await session.refresh(p)
    return p


async def _tx(
    session: AsyncSession,
    user: User,
    account: Account,
    *,
    description: str,
    amount: Decimal = Decimal("10"),
    txn_type: str = "debit",
    category: Category | None = None,
    payee: Payee | None = None,
    transfer_pair_id: uuid.UUID | None = None,
    exclude_from_pnl: bool = False,
    is_ignored: bool = False,
    txn_date: date | None = None,
) -> Transaction:
    tx = Transaction(
        id=uuid.uuid4(),
        user_id=user.id,
        account_id=account.id,
        description=description,
        amount=amount,
        date=txn_date or date.today(),
        type=txn_type,
        source="manual",
        currency="BRL",
        category_id=category.id if category else None,
        payee_id=payee.id if payee else None,
        transfer_pair_id=transfer_pair_id,
        exclude_from_pnl=exclude_from_pnl,
        is_ignored=is_ignored,
    )
    session.add(tx)
    await session.commit()
    await session.refresh(tx)
    return tx


async def _second_workspace_user(session: AsyncSession) -> tuple[User, Workspace]:
    import bcrypt as _bcrypt

    hashed = _bcrypt.hashpw(b"otherpass123", _bcrypt.gensalt()).decode()
    user = User(
        id=uuid.uuid4(),
        email=f"other-{uuid.uuid4().hex[:8]}@example.com",
        hashed_password=hashed,
        is_active=True,
        is_superuser=False,
        is_verified=True,
        preferences={"currency_display": "BRL"},
    )
    session.add(user)
    await session.flush()
    ws = Workspace(
        id=uuid.uuid4(),
        name="Other",
        kind="personal",
        created_by_user_id=user.id,
        default_currency="BRL",
    )
    session.add(ws)
    await session.flush()
    session.add(
        WorkspaceMember(
            id=uuid.uuid4(),
            workspace_id=ws.id,
            user_id=user.id,
            role="owner",
        )
    )
    await session.commit()
    await session.refresh(user)
    return user, ws


@pytest.mark.asyncio
async def test_two_identical_histories_suggest(
    session: AsyncSession, test_user: User, test_workspace: Workspace
):
    acc = await _account(session, test_user, "A")
    food = await _category(session, test_user, "Alimentação")
    await _tx(session, test_user, acc, description="IFOOD *1234", category=food)
    await _tx(session, test_user, acc, description="IFOOD PEDIDO 999", category=food)
    pending = await _tx(session, test_user, acc, description="IFOOD *8472")

    suggestions = await suggest_categories_for_transactions(
        session, test_workspace.id, [pending]
    )
    assert pending.id in suggestions
    s = suggestions[pending.id]
    assert s.category_id == food.id
    assert s.matched_count == 2
    assert s.total_count == 2
    assert s.confidence == 1.0
    assert s.reason_code == "same_merchant"
    assert s.identity_label == "IFOOD"
    assert MIN_SAMPLES == 2
    assert DOMINANT_RATIO == 0.75


@pytest.mark.asyncio
async def test_single_history_does_not_suggest(
    session: AsyncSession, test_user: User, test_workspace: Workspace
):
    acc = await _account(session, test_user, "A")
    food = await _category(session, test_user, "Alimentação")
    await _tx(session, test_user, acc, description="IFOOD *1", category=food)
    pending = await _tx(session, test_user, acc, description="IFOOD *2")

    suggestions = await suggest_categories_for_transactions(
        session, test_workspace.id, [pending]
    )
    assert suggestions == {}


@pytest.mark.asyncio
async def test_consensus_at_75_percent_suggests(
    session: AsyncSession, test_user: User, test_workspace: Workspace
):
    acc = await _account(session, test_user, "A")
    food = await _category(session, test_user, "Alimentação")
    work = await _category(session, test_user, "Trabalho")
    await _tx(session, test_user, acc, description="IFOOD A", category=food)
    await _tx(session, test_user, acc, description="IFOOD B", category=food)
    await _tx(session, test_user, acc, description="IFOOD C", category=food)
    await _tx(session, test_user, acc, description="IFOOD D", category=work)
    pending = await _tx(session, test_user, acc, description="IFOOD E")

    suggestions = await suggest_categories_for_transactions(
        session, test_workspace.id, [pending]
    )
    assert suggestions[pending.id].category_id == food.id
    assert suggestions[pending.id].confidence == 0.75


@pytest.mark.asyncio
async def test_consensus_below_threshold_no_suggestion(
    session: AsyncSession, test_user: User, test_workspace: Workspace
):
    acc = await _account(session, test_user, "A")
    food = await _category(session, test_user, "Alimentação")
    work = await _category(session, test_user, "Trabalho")
    await _tx(session, test_user, acc, description="IFOOD A", category=food)
    await _tx(session, test_user, acc, description="IFOOD B", category=food)
    await _tx(session, test_user, acc, description="IFOOD C", category=work)
    await _tx(session, test_user, acc, description="IFOOD D", category=work)
    # 50% — below 0.75
    pending = await _tx(session, test_user, acc, description="IFOOD E")

    suggestions = await suggest_categories_for_transactions(
        session, test_workspace.id, [pending]
    )
    assert suggestions == {}


@pytest.mark.asyncio
async def test_tie_no_suggestion(
    session: AsyncSession, test_user: User, test_workspace: Workspace
):
    acc = await _account(session, test_user, "A")
    food = await _category(session, test_user, "Alimentação")
    work = await _category(session, test_user, "Trabalho")
    await _tx(session, test_user, acc, description="IFOOD A", category=food)
    await _tx(session, test_user, acc, description="IFOOD B", category=food)
    await _tx(session, test_user, acc, description="IFOOD C", category=work)
    await _tx(session, test_user, acc, description="IFOOD D", category=work)
    pending = await _tx(session, test_user, acc, description="IFOOD E")

    suggestions = await suggest_categories_for_transactions(
        session, test_workspace.id, [pending]
    )
    assert suggestions == {}


@pytest.mark.asyncio
async def test_workspace_isolation(
    session: AsyncSession, test_user: User, test_workspace: Workspace
):
    other_user, other_ws = await _second_workspace_user(session)
    acc_a = await _account(session, test_user, "Mine")
    acc_b = await _account(session, other_user, "Theirs")
    food_a = await _category(session, test_user, "Alimentação")
    food_b = await _category(session, other_user, "Food Other")
    await _tx(session, other_user, acc_b, description="IFOOD *1", category=food_b)
    await _tx(session, other_user, acc_b, description="IFOOD *2", category=food_b)
    pending = await _tx(session, test_user, acc_a, description="IFOOD *3")

    suggestions = await suggest_categories_for_transactions(
        session, test_workspace.id, [pending]
    )
    assert suggestions == {}
    # Sanity: other workspace would see its own history
    other_pending = await _tx(session, other_user, acc_b, description="IFOOD *9")
    other_sugs = await suggest_categories_for_transactions(
        session, other_ws.id, [other_pending]
    )
    assert other_sugs[other_pending.id].category_id == food_b.id


@pytest.mark.asyncio
async def test_history_across_accounts_same_workspace(
    session: AsyncSession, test_user: User, test_workspace: Workspace
):
    nubank = await _account(session, test_user, "Nubank")
    itau = await _account(session, test_user, "Itaú")
    food = await _category(session, test_user, "Alimentação")
    await _tx(session, test_user, nubank, description="IFOOD *1", category=food)
    await _tx(session, test_user, itau, description="IFOOD *2", category=food)
    pending = await _tx(session, test_user, nubank, description="IFOOD *3")

    suggestions = await suggest_categories_for_transactions(
        session, test_workspace.id, [pending]
    )
    assert suggestions[pending.id].category_id == food.id


@pytest.mark.asyncio
async def test_transfer_card_payment_adjustment_excluded(
    session: AsyncSession, test_user: User, test_workspace: Workspace
):
    bank = await _account(session, test_user, "Bank")
    card = await _account(session, test_user, "Card", account_type="credit_card")
    food = await _category(session, test_user, "Alimentação")
    pair = uuid.uuid4()
    # Would look like IFOOD but are transfer / adjustment / ignored
    await _tx(
        session, test_user, bank,
        description="IFOOD PAIR OUT", category=food, transfer_pair_id=pair,
    )
    await _tx(
        session, test_user, card,
        description="IFOOD PAIR IN", category=food, transfer_pair_id=pair,
    )
    await _tx(
        session, test_user, bank,
        description="IFOOD AJUSTE", category=food, exclude_from_pnl=True,
    )
    await _tx(
        session, test_user, bank,
        description="IFOOD IGNORED", category=food, is_ignored=True,
    )
    pending = await _tx(session, test_user, bank, description="IFOOD NEW")

    suggestions = await suggest_categories_for_transactions(
        session, test_workspace.id, [pending]
    )
    assert suggestions == {}


@pytest.mark.asyncio
async def test_treat_as_transfer_and_ignored_category_excluded(
    session: AsyncSession, test_user: User, test_workspace: Workspace
):
    acc = await _account(session, test_user, "A")
    transfer_cat = await _category(
        session, test_user, "Transfers", treat_as_transfer=True
    )
    ignored_cat = await _category(
        session, test_user, "Hidden", is_ignored=True
    )
    await _tx(session, test_user, acc, description="IFOOD T1", category=transfer_cat)
    await _tx(session, test_user, acc, description="IFOOD T2", category=transfer_cat)
    await _tx(session, test_user, acc, description="IFOOD I1", category=ignored_cat)
    await _tx(session, test_user, acc, description="IFOOD I2", category=ignored_cat)
    pending = await _tx(session, test_user, acc, description="IFOOD NEW")

    suggestions = await suggest_categories_for_transactions(
        session, test_workspace.id, [pending]
    )
    assert suggestions == {}


@pytest.mark.asyncio
async def test_payee_id_exact_preferred(
    session: AsyncSession, test_user: User, test_workspace: Workspace
):
    acc = await _account(session, test_user, "A")
    food = await _category(session, test_user, "Alimentação")
    streaming = await _category(session, test_user, "Streaming")
    ifood_payee = await _payee(session, test_user, "iFood")
    # Signature history would suggest Streaming if we only looked at NETFLIX-like
    # noise — but payee history should win for this payee.
    await _tx(
        session, test_user, acc,
        description="RANDOM MEMO 1", category=food, payee=ifood_payee,
    )
    await _tx(
        session, test_user, acc,
        description="RANDOM MEMO 2", category=food, payee=ifood_payee,
    )
    await _tx(session, test_user, acc, description="OTHER MERCHANT X", category=streaming)
    await _tx(session, test_user, acc, description="OTHER MERCHANT Y", category=streaming)
    pending = await _tx(
        session, test_user, acc,
        description="RANDOM MEMO 3", payee=ifood_payee,
    )

    suggestions = await suggest_categories_for_transactions(
        session, test_workspace.id, [pending]
    )
    assert suggestions[pending.id].category_id == food.id
    assert suggestions[pending.id].reason_code == "same_payee"


@pytest.mark.asyncio
async def test_different_merchants_do_not_collide(
    session: AsyncSession, test_user: User, test_workspace: Workspace
):
    acc = await _account(session, test_user, "A")
    food = await _category(session, test_user, "Alimentação")
    transport = await _category(session, test_user, "Transporte")
    await _tx(session, test_user, acc, description="UBER TRIP 1", category=transport)
    await _tx(session, test_user, acc, description="UBER TRIP 2", category=transport)
    await _tx(session, test_user, acc, description="IFOOD *1", category=food)
    await _tx(session, test_user, acc, description="IFOOD *2", category=food)
    pending = await _tx(session, test_user, acc, description="IFOOD *3")

    suggestions = await suggest_categories_for_transactions(
        session, test_workspace.id, [pending]
    )
    assert suggestions[pending.id].category_id == food.id


@pytest.mark.asyncio
async def test_batch_suggestion_bounded_queries(
    session: AsyncSession, test_user: User, test_workspace: Workspace
):
    """50 pendings must not issue one history query each."""
    acc = await _account(session, test_user, "A")
    food = await _category(session, test_user, "Alimentação")
    await _tx(session, test_user, acc, description="IFOOD HIST 1", category=food)
    await _tx(session, test_user, acc, description="IFOOD HIST 2", category=food)

    pendings = [
        await _tx(session, test_user, acc, description=f"IFOOD NEW {i}")
        for i in range(50)
    ]

    sync_conn = await session.connection()
    sync_engine = sync_conn.sync_connection.engine
    statements: list[str] = []

    def _count(conn, cursor, statement, parameters, context, executemany):
        statements.append(statement)

    event.listen(sync_engine, "before_cursor_execute", _count)
    try:
        suggestions = await suggest_categories_for_transactions(
            session, test_workspace.id, pendings
        )
    finally:
        event.remove(sync_engine, "before_cursor_execute", _count)

    # At most 2 history queries (payee + signature). Payee set empty → 1 query.
    assert len(statements) <= 2
    assert len(suggestions) == 50


@pytest.mark.asyncio
async def test_api_include_suggestions_flag(
    client: AsyncClient,
    auth_headers: dict,
    session: AsyncSession,
    test_user: User,
):
    acc = await _account(session, test_user, "API Acc")
    food = await _category(session, test_user, "Alimentação")
    await _tx(session, test_user, acc, description="IFOOD *1", category=food)
    await _tx(session, test_user, acc, description="IFOOD *2", category=food)
    await _tx(session, test_user, acc, description="IFOOD *8472")

    without = await client.get(
        "/api/transactions?uncategorized=true",
        headers=auth_headers,
    )
    assert without.status_code == 200
    assert without.json()["items"][0].get("category_suggestion") is None

    with_sug = await client.get(
        "/api/transactions?uncategorized=true&include_suggestions=true",
        headers=auth_headers,
    )
    assert with_sug.status_code == 200
    item = next(
        i for i in with_sug.json()["items"] if i["description"] == "IFOOD *8472"
    )
    assert item["category_suggestion"]["category_name"] == "Alimentação"
    assert item["category_suggestion"]["matched_count"] == 2
    assert item["category_suggestion"]["reason_code"] == "same_merchant"
    assert item["category_id"] is None  # never auto-applied


@pytest.mark.asyncio
async def test_merchant_key_variants_suggest_same_category(
    session: AsyncSession, test_user: User, test_workspace: Workspace
):
    acc = await _account(session, test_user, "A")
    food = await _category(session, test_user, "Alimentação")
    await _tx(session, test_user, acc, description="PIX QR CODE IFOOD 1", category=food)
    await _tx(session, test_user, acc, description="PGTO IFOOD", category=food)
    pending = await _tx(session, test_user, acc, description="COMPRA IFOOD SA")

    suggestions = await suggest_categories_for_transactions(
        session, test_workspace.id, [pending]
    )
    assert suggestions[pending.id].reason_code == "same_merchant"
    assert suggestions[pending.id].category_id == food.id


@pytest.mark.asyncio
async def test_mercado_livre_alias_history_matches(
    session: AsyncSession, test_user: User, test_workspace: Workspace
):
    acc = await _account(session, test_user, "A")
    shopping = await _category(session, test_user, "Compras")
    await _tx(session, test_user, acc, description="MERCADO LIVRE", category=shopping)
    await _tx(session, test_user, acc, description="MP *MERCADOLIVRE", category=shopping)
    pending = await _tx(session, test_user, acc, description="MERCADOLIVRE")

    suggestions = await suggest_categories_for_transactions(
        session, test_workspace.id, [pending]
    )
    assert suggestions[pending.id].category_id == shopping.id
    assert suggestions[pending.id].identity_label == "MERCADO LIVRE"


@pytest.mark.asyncio
async def test_recency_window_prefers_recent_categories(
    session: AsyncSession, test_user: User, test_workspace: Workspace
):
    """Older history outside the recent window must not dominate consensus."""
    from datetime import timedelta

    from app.services.category_suggestion_service import RECENT_MATCH_LIMIT

    acc = await _account(session, test_user, "A")
    leisure = await _category(session, test_user, "Lazer")
    subs = await _category(session, test_user, "Assinaturas")
    old = date.today() - timedelta(days=400)
    recent = date.today()

    # Flood of old leisure classifications (more than the window size)
    for i in range(RECENT_MATCH_LIMIT + 5):
        await _tx(
            session, test_user, acc,
            description=f"NETFLIX OLD {i}",
            category=leisure,
            txn_date=old,
        )
    # Fill the entire recent window with Assinaturas
    for i in range(RECENT_MATCH_LIMIT):
        await _tx(
            session, test_user, acc,
            description=f"NETFLIX NEW {i}",
            category=subs,
            txn_date=recent,
        )
    pending = await _tx(session, test_user, acc, description="NETFLIX 999")

    suggestions = await suggest_categories_for_transactions(
        session, test_workspace.id, [pending]
    )
    assert suggestions[pending.id].category_id == subs.id
    assert suggestions[pending.id].total_count <= RECENT_MATCH_LIMIT


@pytest.mark.asyncio
async def test_natural_consensus_shift_after_new_categorizations(
    session: AsyncSession, test_user: User, test_workspace: Workspace
):
    from app.services.category_suggestion_service import RECENT_MATCH_LIMIT

    acc = await _account(session, test_user, "A")
    food = await _category(session, test_user, "Alimentação")
    work = await _category(session, test_user, "Trabalho")
    for i in range(3):
        await _tx(session, test_user, acc, description=f"IFOOD F{i}", category=food)

    pending1 = await _tx(session, test_user, acc, description="IFOOD NEXT1")
    s1 = await suggest_categories_for_transactions(
        session, test_workspace.id, [pending1]
    )
    assert s1[pending1.id].category_id == food.id

    # Categorize pending1 as food so it stays in history, then flood Trabalho
    pending1.category_id = food.id
    await session.commit()

    for i in range(RECENT_MATCH_LIMIT):
        await _tx(session, test_user, acc, description=f"IFOOD WORK {i}", category=work)

    pending2 = await _tx(session, test_user, acc, description="IFOOD NEXT2")
    s2 = await suggest_categories_for_transactions(
        session, test_workspace.id, [pending2]
    )
    assert s2[pending2.id].category_id == work.id
    assert s2[pending2.id].reason_code == "same_merchant"


@pytest.mark.asyncio
async def test_payee_still_outranks_merchant(
    session: AsyncSession, test_user: User, test_workspace: Workspace
):
    acc = await _account(session, test_user, "A")
    food = await _category(session, test_user, "Alimentação")
    streaming = await _category(session, test_user, "Streaming")
    payee = await _payee(session, test_user, "Custom Payee")
    await _tx(
        session, test_user, acc,
        description="IFOOD *1", category=streaming, payee=payee,
    )
    await _tx(
        session, test_user, acc,
        description="IFOOD *2", category=streaming, payee=payee,
    )
    # Merchant history alone would prefer food
    await _tx(session, test_user, acc, description="IFOOD X1", category=food)
    await _tx(session, test_user, acc, description="IFOOD X2", category=food)
    pending = await _tx(
        session, test_user, acc, description="IFOOD *3", payee=payee
    )

    suggestions = await suggest_categories_for_transactions(
        session, test_workspace.id, [pending]
    )
    assert suggestions[pending.id].category_id == streaming.id
    assert suggestions[pending.id].reason_code == "same_payee"
