"""Derived financial classification for transactions.

``Transaction.type`` remains the ledger direction (``debit`` / ``credit``).
This module answers a different question: what does the movement *mean*
for personal-finance reporting?

Classification is computed from already-loaded fields — never from the
database. Callers that need counterpart account types for paired legs must
supply them (typically via a single batched lookup) so list endpoints can
avoid N+1 queries.

Precedence (first match wins):

1. ``adjustment`` — ``exclude_from_pnl``
2. ``card_payment`` — paired cash ↔ credit_card
3. ``transfer`` — other pairs, or category ``treat_as_transfer``
4. ``uncertain`` — no category (pending categorization)
5. ``income`` — credit
6. ``expense`` — debit

``is_ignored`` is intentionally **orthogonal** to classification. Ignoring
hides a row from balance/P&L totals; it does not redefine whether the
underlying event was spending, income, or a transfer. Use list filters /
``counts_as_pnl`` for exclusion — not this classifier.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from typing import Iterable, Literal, Optional, Sequence

TransactionClassification = Literal[
    "income",
    "expense",
    "transfer",
    "card_payment",
    "adjustment",
    "uncertain",
]

CLASSIFICATIONS: frozenset[str] = frozenset(
    ("income", "expense", "transfer", "card_payment", "adjustment", "uncertain")
)

_CASH_ACCOUNT_TYPES = frozenset({"checking", "savings"})
_CARD_ACCOUNT_TYPE = "credit_card"


@dataclass(frozen=True, slots=True)
class ClassificationInput:
    """Preloaded facts needed to classify one transaction.

    ``counterpart_account_type`` is required for accurate ``card_payment``
    detection when ``transfer_pair_id`` is set. If omitted on a paired row,
    the classifier falls back to ``transfer`` (never invents card_payment
    without structural evidence).
    """

    type: str  # debit | credit
    account_type: str
    category_id: Optional[uuid.UUID] = None
    treat_as_transfer: bool = False
    transfer_pair_id: Optional[uuid.UUID] = None
    counterpart_account_type: Optional[str] = None
    exclude_from_pnl: bool = False
    is_ignored: bool = False  # orthogonal to classification; see module docstring


def is_cash_account_type(account_type: str | None) -> bool:
    return (account_type or "") in _CASH_ACCOUNT_TYPES


def is_card_account_type(account_type: str | None) -> bool:
    return (account_type or "") == _CARD_ACCOUNT_TYPE


def is_card_payment_pair(
    account_type: str | None,
    counterpart_account_type: str | None,
) -> bool:
    """True when the two account types form a bank/savings ↔ credit-card pair."""
    if not account_type or not counterpart_account_type:
        return False
    a_cash = is_cash_account_type(account_type)
    b_cash = is_cash_account_type(counterpart_account_type)
    a_card = is_card_account_type(account_type)
    b_card = is_card_account_type(counterpart_account_type)
    return (a_cash and b_card) or (a_card and b_cash)


def classify_transaction(data: ClassificationInput) -> TransactionClassification:
    """Return the financial meaning of one transaction (pure / deterministic)."""
    # 1. Balance adjustment kept in the ledger but omitted from P&L.
    if data.exclude_from_pnl:
        return "adjustment"

    # 2–3. Structural pairing beats category and uncategorized state.
    if data.transfer_pair_id is not None:
        if is_card_payment_pair(data.account_type, data.counterpart_account_type):
            return "card_payment"
        return "transfer"

    # Unilateral "flows, not spend" — category flag, no pair required.
    if data.treat_as_transfer:
        return "transfer"

    # 4. Pending categorization (not an error).
    if data.category_id is None:
        return "uncertain"

    # 5–6. Ledger direction once meaning is ordinary income/expense.
    if data.type == "credit":
        return "income"
    if data.type == "debit":
        return "expense"

    # Defensive: unknown type strings stay reviewable rather than inventing spend.
    return "uncertain"


def classify_transactions(
    rows: Sequence[ClassificationInput],
) -> list[TransactionClassification]:
    """Batch classify preloaded rows — no I/O."""
    return [classify_transaction(row) for row in rows]


def group_pair_legs(
    legs: Iterable[tuple[uuid.UUID, uuid.UUID, str]],
) -> dict[uuid.UUID, list[tuple[uuid.UUID, str]]]:
    """Group ``(transfer_pair_id, account_id, account_type)`` for batch classify.

    Use with :func:`counterpart_account_type_for` after one query that loads
    all paired siblings in a page of results.
    """
    grouped: dict[uuid.UUID, list[tuple[uuid.UUID, str]]] = {}
    for pair_id, account_id, account_type in legs:
        grouped.setdefault(pair_id, []).append((account_id, account_type))
    return grouped


def counterpart_account_type_for(
    *,
    transfer_pair_id: uuid.UUID,
    account_id: uuid.UUID,
    pair_legs: dict[uuid.UUID, list[tuple[uuid.UUID, str]]],
) -> Optional[str]:
    """Given legs grouped by pair id, return the other account's type."""
    for other_account_id, other_type in pair_legs.get(transfer_pair_id) or []:
        if other_account_id != account_id:
            return other_type
    return None


def input_from_orm(
    tx: object,
    counterpart_account_type: Optional[str] = None,
) -> ClassificationInput:
    """Build :class:`ClassificationInput` from an ORM Transaction (and relations).

    Expects ``tx.account`` / ``tx.category`` already loaded when needed — callers
    must not trigger lazy loads under async sessions.
    """
    account = getattr(tx, "account", None)
    category = getattr(tx, "category", None)
    return ClassificationInput(
        type=str(getattr(tx, "type", "") or ""),
        account_type=str(getattr(account, "type", None) or ""),
        category_id=getattr(tx, "category_id", None),
        treat_as_transfer=bool(getattr(category, "treat_as_transfer", False)),
        transfer_pair_id=getattr(tx, "transfer_pair_id", None),
        counterpart_account_type=counterpart_account_type,
        exclude_from_pnl=bool(getattr(tx, "exclude_from_pnl", False)),
        is_ignored=bool(getattr(tx, "is_ignored", False)),
    )


def classify_orm(
    tx: object,
    counterpart_account_type: Optional[str] = None,
) -> TransactionClassification:
    """Classify a loaded ORM transaction using the pure helper."""
    return classify_transaction(input_from_orm(tx, counterpart_account_type))
