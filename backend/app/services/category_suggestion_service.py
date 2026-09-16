"""Historical category suggestions (Epics 3A / 3B).

Principle: history produces a SUGGESTION, never an automatic decision.
No Transaction column is written; callers must PATCH after user consent.

Consensus thresholds (service constants — not DB fields):
  MIN_SAMPLES = 2
  DOMINANT_RATIO = 0.75
  RECENT_MATCH_LIMIT = 20   # Epic 3B: only the newest matching rows count

Match order (deterministic, explainable):
  1. Exact payee_id within the workspace
  2. Derived merchant_key (Epic 3B)
  3. Legacy description signature (Epic 3A fallback)
  4. No suggestion

Recency (Epic 3B decision):
  Option A — last N matching occurrences (N=20), ordered by date DESC then id.
  Older matches are ignored so preference drift shows up without weighted math.
  Equal weight within that window. Documented + tested.

Exclusions from learning history:
  - transfer_pair_id IS NOT NULL (covers transfer + card_payment pairs)
  - exclude_from_pnl (adjustment)
  - is_ignored
  - category.treat_as_transfer / category.is_ignored
  - category_id IS NULL

Batch design: at most two history queries for a page of pendings
(payee_id IN (…) and description ILIKE any merchant/signature needle).
Never one query per transaction.

Observability: the project has no metrics/telemetry pipeline for this path.
We intentionally do not log descriptions, amounts, or tax ids, and do not
add analytics infrastructure in this epic.
"""

from __future__ import annotations

import uuid
from collections import Counter, defaultdict
from dataclasses import dataclass
from datetime import date
from typing import Iterable, Literal, Optional

from sqlalchemy import Select, not_, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.category import Category
from app.models.transaction import Transaction
from app.schemas.transaction import CategorySuggestion
from app.services.description_signature import (
    derive_merchant_key,
    description_matches_merchant_key,
    description_matches_signature,
    extract_stable_description_term,
    merchant_key_search_needles,
)

# --- Tunable consensus (document in module docstring; keep out of DB) ---
MIN_SAMPLES = 2
DOMINANT_RATIO = 0.75
RECENT_MATCH_LIMIT = 20

ReasonCode = Literal[
    "same_payee",
    "same_merchant",
    "same_description_signature",
    "similar_description",  # retained for API compatibility (3A clients)
]


@dataclass(frozen=True)
class _HistoryRow:
    id: uuid.UUID
    payee_id: Optional[uuid.UUID]
    description: str
    category_id: uuid.UUID
    category_name: str
    date: date


def _consensus(
    category_counts: Counter[uuid.UUID],
    names: dict[uuid.UUID, str],
    *,
    min_samples: int = MIN_SAMPLES,
    dominant_ratio: float = DOMINANT_RATIO,
) -> tuple[uuid.UUID, str, int, int, float] | None:
    """Return (category_id, name, matched, total, confidence) or None."""
    total = sum(category_counts.values())
    if total < min_samples:
        return None
    top = category_counts.most_common(2)
    dominant_id, dominant_count = top[0]
    # Tie for first place → no suggestion
    if len(top) >= 2 and top[0][1] == top[1][1]:
        return None
    ratio = dominant_count / total
    if ratio < dominant_ratio:
        return None
    name = names.get(dominant_id)
    if not name:
        return None
    return dominant_id, name, dominant_count, total, ratio


def _recent_slice(rows: list[_HistoryRow]) -> list[_HistoryRow]:
    """Keep only the newest RECENT_MATCH_LIMIT rows (date DESC, id DESC)."""
    ordered = sorted(rows, key=lambda r: (r.date, r.id), reverse=True)
    return ordered[:RECENT_MATCH_LIMIT]


def _reason_text(
    code: ReasonCode,
    category_name: str,
    matched: int,
    total: int,
    *,
    identity_label: str | None = None,
) -> str:
    if code == "same_payee":
        return (
            f"{matched} of {total} transactions with the same payee "
            f"were categorized as {category_name}"
        )
    if code == "same_merchant":
        label = identity_label or "this merchant"
        return (
            f"{matched} of {total} recent transactions for {label} "
            f"were categorized as {category_name}"
        )
    return (
        f"{matched} of {total} similar transactions "
        f"were categorized as {category_name}"
    )


def _build_suggestion(
    *,
    code: ReasonCode,
    category_id: uuid.UUID,
    category_name: str,
    matched: int,
    total: int,
    confidence: float,
    identity_label: str | None = None,
) -> CategorySuggestion:
    return CategorySuggestion(
        category_id=category_id,
        category_name=category_name,
        reason=_reason_text(
            code, category_name, matched, total, identity_label=identity_label
        ),
        reason_code=code,
        matched_count=matched,
        total_count=total,
        confidence=round(confidence, 4),
        identity_label=identity_label,
    )


def _learning_history_query(workspace_id: uuid.UUID) -> Select:
    """Base SELECT for categorized rows eligible as learning history."""
    return (
        select(
            Transaction.id,
            Transaction.payee_id,
            Transaction.description,
            Transaction.category_id,
            Category.name,
            Transaction.date,
        )
        .join(Category, Category.id == Transaction.category_id)
        .where(
            Transaction.workspace_id == workspace_id,
            Transaction.category_id.is_not(None),
            Transaction.transfer_pair_id.is_(None),
            Transaction.exclude_from_pnl.is_(False),
            Transaction.is_ignored.is_(False),
            Category.treat_as_transfer.is_(False),
            Category.is_ignored.is_(False),
            Category.workspace_id == workspace_id,
        )
    )


def _escape_like(value: str) -> str:
    return value.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")


def _rows_from_result(rows) -> list[_HistoryRow]:
    return [
        _HistoryRow(
            id=r.id,
            payee_id=r.payee_id,
            description=r.description or "",
            category_id=r.category_id,
            category_name=r.name,
            date=r.date,
        )
        for r in rows
        if r.category_id is not None
    ]


async def _fetch_payee_history(
    session: AsyncSession,
    workspace_id: uuid.UUID,
    payee_ids: set[uuid.UUID],
    exclude_ids: set[uuid.UUID],
) -> list[_HistoryRow]:
    if not payee_ids:
        return []
    q = _learning_history_query(workspace_id).where(
        Transaction.payee_id.in_(payee_ids)
    )
    if exclude_ids:
        q = q.where(not_(Transaction.id.in_(exclude_ids)))
    return _rows_from_result((await session.execute(q)).all())


async def _fetch_description_history(
    session: AsyncSession,
    workspace_id: uuid.UUID,
    needles: set[str],
    exclude_ids: set[uuid.UUID],
) -> list[_HistoryRow]:
    if not needles:
        return []
    like_clauses = [
        Transaction.description.ilike(f"%{_escape_like(n)}%", escape="\\")
        for n in needles
    ]
    q = _learning_history_query(workspace_id).where(or_(*like_clauses))
    if exclude_ids:
        q = q.where(not_(Transaction.id.in_(exclude_ids)))
    return _rows_from_result((await session.execute(q)).all())


def _suggest_from_counts(
    rows: list[_HistoryRow],
    *,
    code: ReasonCode,
    identity_label: str | None = None,
    min_samples: int = MIN_SAMPLES,
    dominant_ratio: float = DOMINANT_RATIO,
) -> CategorySuggestion | None:
    recent = _recent_slice(rows)
    counts: Counter[uuid.UUID] = Counter()
    names: dict[uuid.UUID, str] = {}
    for row in recent:
        counts[row.category_id] += 1
        names[row.category_id] = row.category_name
    result = _consensus(
        counts, names, min_samples=min_samples, dominant_ratio=dominant_ratio
    )
    if result is None:
        return None
    cat_id, name, matched, total, conf = result
    return _build_suggestion(
        code=code,
        category_id=cat_id,
        category_name=name,
        matched=matched,
        total=total,
        confidence=conf,
        identity_label=identity_label,
    )


def _suggest_from_payee(
    payee_id: uuid.UUID,
    history: Iterable[_HistoryRow],
) -> CategorySuggestion | None:
    rows = [row for row in history if row.payee_id == payee_id]
    return _suggest_from_counts(rows, code="same_payee")


def _suggest_from_merchant(
    merchant_key: str,
    history: Iterable[_HistoryRow],
    *,
    min_samples: int = MIN_SAMPLES,
) -> CategorySuggestion | None:
    rows = [
        row
        for row in history
        if description_matches_merchant_key(row.description, merchant_key)
    ]
    return _suggest_from_counts(
        rows,
        code="same_merchant",
        identity_label=merchant_key,
        min_samples=min_samples,
    )


def _suggest_from_signature(
    signature: str,
    history: Iterable[_HistoryRow],
    *,
    min_samples: int = MIN_SAMPLES,
) -> CategorySuggestion | None:
    rows = [
        row
        for row in history
        if description_matches_signature(row.description, signature)
    ]
    # Prefer the explicit 3B code; keep similar_description unused for new paths.
    return _suggest_from_counts(
        rows, code="same_description_signature", min_samples=min_samples
    )


def _normalize_memo(description: str) -> str:
    return " ".join((description or "").casefold().split())


def _suggest_exact_memo(
    description: str,
    history: Iterable[_HistoryRow],
) -> CategorySuggestion | None:
    """One prior identical memo is enough to prefill a new import row."""
    needle = _normalize_memo(description)
    if not needle:
        return None
    rows = [row for row in history if _normalize_memo(row.description) == needle]
    return _suggest_from_counts(
        rows,
        code="same_description_signature",
        identity_label=needle[:64] or None,
        min_samples=1,
    )


def _identity_for_description(description: str) -> tuple[str | None, str | None]:
    merchant = derive_merchant_key(description)
    signature = extract_stable_description_term(description)
    if merchant and signature and (
        merchant == signature or signature in merchant.split()
    ):
        signature = None
    return merchant, signature


async def suggest_categories_for_import_descriptions(
    session: AsyncSession,
    workspace_id: uuid.UUID,
    descriptions: list[str],
) -> list[CategorySuggestion | None]:
    """Prefill import-review categories from workspace history.

    Unlike the pending-inbox path (MIN_SAMPLES=2), import accepts a single
    prior categorization for the same memo/merchant so a second statement
    file inherits what the user already confirmed.
    """
    if not descriptions:
        return []

    needles: set[str] = set()
    identities: list[tuple[str | None, str | None]] = []
    for desc in descriptions:
        merchant, signature = _identity_for_description(desc)
        identities.append((merchant, signature))
        if merchant:
            needles.update(merchant_key_search_needles(merchant))
        if signature:
            needles.add(signature)
        # Exact-memo lookup still benefits from a coarse ILIKE needle.
        token = extract_stable_description_term(desc)
        if token:
            needles.add(token)
        compact = _normalize_memo(desc)
        if compact and len(compact) >= 4:
            needles.add(compact[:48])

    history = await _fetch_description_history(
        session, workspace_id, needles, exclude_ids=set()
    )

    out: list[CategorySuggestion | None] = []
    for desc, (merchant, signature) in zip(descriptions, identities):
        suggestion = _suggest_exact_memo(desc, history)
        if suggestion is None and merchant:
            suggestion = _suggest_from_merchant(merchant, history, min_samples=1)
        if suggestion is None and signature:
            suggestion = _suggest_from_signature(signature, history, min_samples=1)
        out.append(suggestion)
    return out


def _identity_for_tx(tx: Transaction) -> tuple[str | None, str | None]:
    """Return (merchant_key, signature_fallback)."""
    text = tx.description or tx.original_description
    merchant = derive_merchant_key(tx.description) or derive_merchant_key(
        tx.original_description
    )
    signature = extract_stable_description_term(text)
    # Avoid double-counting: if merchant equals signature, signature is redundant.
    if merchant and signature and (
        merchant == signature or signature in merchant.split()
    ):
        signature = None
    return merchant, signature


async def suggest_categories_for_transactions(
    session: AsyncSession,
    workspace_id: uuid.UUID,
    transactions: list[Transaction],
) -> dict[uuid.UUID, CategorySuggestion]:
    """Batch-suggest categories for uncategorized transactions.

    Already-categorized rows are skipped (no suggestion field needed).
    """
    pending = [tx for tx in transactions if tx.category_id is None]
    if not pending:
        return {}

    exclude_ids = {tx.id for tx in pending}
    payee_ids = {tx.payee_id for tx in pending if tx.payee_id is not None}

    merchants: dict[uuid.UUID, str] = {}
    signatures: dict[uuid.UUID, str] = {}
    needles: set[str] = set()
    for tx in pending:
        merchant, signature = _identity_for_tx(tx)
        if merchant:
            merchants[tx.id] = merchant
            needles.update(merchant_key_search_needles(merchant))
        if signature:
            signatures[tx.id] = signature
            needles.add(signature)

    payee_history = await _fetch_payee_history(
        session, workspace_id, payee_ids, exclude_ids
    )
    desc_history = await _fetch_description_history(
        session, workspace_id, needles, exclude_ids
    )

    by_payee: dict[uuid.UUID, list[_HistoryRow]] = defaultdict(list)
    for row in payee_history:
        if row.payee_id is not None:
            by_payee[row.payee_id].append(row)

    out: dict[uuid.UUID, CategorySuggestion] = {}
    for tx in pending:
        suggestion: CategorySuggestion | None = None
        if tx.payee_id is not None:
            suggestion = _suggest_from_payee(tx.payee_id, by_payee.get(tx.payee_id, []))
        if suggestion is None:
            merchant = merchants.get(tx.id)
            if merchant:
                suggestion = _suggest_from_merchant(merchant, desc_history)
        if suggestion is None:
            signature = signatures.get(tx.id)
            if signature:
                suggestion = _suggest_from_signature(signature, desc_history)
        if suggestion is not None:
            out[tx.id] = suggestion
    return out
