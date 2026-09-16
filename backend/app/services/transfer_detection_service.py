import re
import unicodedata
import uuid
from collections import defaultdict
from decimal import Decimal
from typing import Optional

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.account import Account
from app.models.transaction import Transaction

# Minimum confidence before auto-pairing. Amount + date alone is never enough
# for cash↔cash; description hints and/or bank↔card structure must push the
# score over this threshold. Ambiguous ties never auto-pair.
_MIN_PAIR_SCORE = 2

# Keywords that raise confidence a match is an own-account transfer or a
# credit-card bill payment. Accent-insensitive; matched as substrings after
# normalization. Description never forces a pair by itself — it only
# contributes score.
_TRANSFER_HINTS = (
    "pix",
    "ted",
    "doc",
    "transfer",
    "transf",
    "transferencia",
    "pagamento cartao",
    "pagamento fatura",
    "pgto cartao",
    "pgto fatura",
    "pagto cartao",
    "pagto fatura",
    "card payment",
    "bill payment",
    "credit card payment",
)

_CASH_ACCOUNT_TYPES = frozenset({"checking", "savings"})
_CARD_ACCOUNT_TYPE = "credit_card"


def _normalize_desc(text: str | None) -> str:
    """Lowercase, strip accents, collapse whitespace for hint matching."""
    if not text:
        return ""
    decomposed = unicodedata.normalize("NFKD", text)
    ascii_text = "".join(ch for ch in decomposed if not unicodedata.combining(ch))
    return re.sub(r"\s+", " ", ascii_text.lower()).strip()


def _has_transfer_hint(description: str | None) -> bool:
    normalized = _normalize_desc(description)
    if not normalized:
        return False
    return any(hint in normalized for hint in _TRANSFER_HINTS)


def _abs_amount(amount) -> Decimal:
    """Money key as Decimal — never float."""
    return abs(Decimal(str(amount)))


def _pair_score(
    debit: Transaction,
    credit: Transaction,
    account_types: dict[uuid.UUID, str],
) -> int:
    """Confidence score for auto-pairing two opposite legs.

    Returns 0 when the pair must not be formed automatically.
    """
    debit_type = account_types.get(debit.account_id, "")
    credit_type = account_types.get(credit.account_id, "")

    score = 0
    debit_hint = _has_transfer_hint(debit.description)
    credit_hint = _has_transfer_hint(credit.description)

    if debit_hint and credit_hint:
        score += 2
    elif debit_hint or credit_hint:
        score += 1

    # Structural signal for bill payments: cash account ↔ credit card.
    cash_to_card = (
        debit_type in _CASH_ACCOUNT_TYPES and credit_type == _CARD_ACCOUNT_TYPE
    )
    card_to_cash = (
        debit_type == _CARD_ACCOUNT_TYPE and credit_type in _CASH_ACCOUNT_TYPES
    )
    if cash_to_card or card_to_cash:
        score += 1

    return score


async def detect_transfer_pairs(
    session: AsyncSession,
    workspace_id: uuid.UUID,
    candidate_ids: Optional[list[uuid.UUID]] = None,
    date_tolerance_days: int = 2,
) -> int:
    """Detect inter-account transfer pairs and link them with a shared UUID.

    Algorithm:
    1. When candidate_ids is given, load candidate debits AND candidate credits
       so that detection works regardless of which side was just imported
       ("at least one leg is new").
    2. For each debit, find unpaired credits with: different account, opposite
       type (debit↔credit), same absolute Decimal amount, date within
       ±tolerance days.
    3. Score each candidate (transfer-like descriptions, bank↔card structure).
       Auto-pair only when exactly one candidate reaches the minimum score —
       ties and low-confidence amount/date-only matches are left for manual
       review.
    4. Already-paired transactions are ignored.

    Returns the number of pairs created.
    """
    # Load candidate debits — filtered to candidate_ids when provided
    debit_query = select(Transaction).where(
        Transaction.workspace_id == workspace_id,
        Transaction.type == "debit",
        Transaction.transfer_pair_id.is_(None),
        Transaction.source != "opening_balance",
    )
    if candidate_ids:
        debit_query = debit_query.where(Transaction.id.in_(candidate_ids))

    debit_result = await session.execute(debit_query)
    debits = list(debit_result.scalars().all())

    # When candidate_ids is given, also load ALL unpaired debits that could
    # match new credits (the reverse direction).
    if candidate_ids:
        reverse_debit_query = select(Transaction).where(
            Transaction.workspace_id == workspace_id,
            Transaction.type == "debit",
            Transaction.transfer_pair_id.is_(None),
            Transaction.source != "opening_balance",
            Transaction.id.not_in(candidate_ids),
        )
        reverse_result = await session.execute(reverse_debit_query)
        reverse_debits = list(reverse_result.scalars().all())
    else:
        reverse_debits = []

    all_debits = debits + reverse_debits

    if not all_debits:
        return 0

    # Load all unpaired credits for the workspace (potential partners)
    credit_query = select(Transaction).where(
        Transaction.workspace_id == workspace_id,
        Transaction.type == "credit",
        Transaction.transfer_pair_id.is_(None),
        Transaction.source != "opening_balance",
    )
    credit_result = await session.execute(credit_query)
    credits = list(credit_result.scalars().all())

    if not credits:
        return 0

    # When candidate_ids is given, restrict reverse debits to only match
    # credits that are in candidate_ids (avoid pairing two old transactions).
    candidate_id_set = set(candidate_ids) if candidate_ids else None

    account_ids = {tx.account_id for tx in all_debits} | {tx.account_id for tx in credits}
    account_result = await session.execute(
        select(Account.id, Account.type).where(Account.id.in_(account_ids))
    )
    account_types = {row.id: row.type for row in account_result.all()}

    # Build a lookup: Decimal amount -> list of credits (never float)
    credit_by_amount: dict[Decimal, list[Transaction]] = defaultdict(list)
    for c in credits:
        credit_by_amount[_abs_amount(c.amount)].append(c)

    paired_credit_ids: set[uuid.UUID] = set()
    pairs_created = 0

    for debit in all_debits:
        debit_amount = _abs_amount(debit.amount)
        amount_candidates = credit_by_amount.get(debit_amount, [])

        is_reverse_debit = candidate_id_set is not None and debit.id not in candidate_id_set

        # Collect every credit that passes hard filters and scores high enough.
        # Auto-pair only when exactly one remains at the top score.
        scored: list[tuple[int, int, Transaction]] = []

        for credit in amount_candidates:
            if credit.id in paired_credit_ids:
                continue
            if credit.account_id == debit.account_id:
                continue
            # Reverse debits may only match credits from candidate_ids
            if is_reverse_debit and candidate_id_set and credit.id not in candidate_id_set:
                continue

            delta = abs((credit.date - debit.date).days)
            if delta > date_tolerance_days:
                continue

            score = _pair_score(debit, credit, account_types)
            if score < _MIN_PAIR_SCORE:
                continue

            scored.append((score, delta, credit))

        if not scored:
            continue

        max_score = max(item[0] for item in scored)
        top = [item for item in scored if item[0] == max_score]
        # Among equal confidence, prefer the closest date — but only when that
        # closest delta is unique. Two same-score / same-day candidates stay
        # unpaired for manual review.
        min_delta = min(item[1] for item in top)
        closest = [item for item in top if item[1] == min_delta]
        if len(closest) != 1:
            continue

        _score, _delta, best_match = closest[0]
        pair_id = uuid.uuid4()
        debit.transfer_pair_id = pair_id
        best_match.transfer_pair_id = pair_id
        # CC statement credits are imported with exclude_from_pnl so they
        # act as fatura abatements until paired. Once linked to the bank
        # debit, clear the flag so classification can surface card_payment.
        if getattr(debit, "exclude_from_pnl", False):
            debit.exclude_from_pnl = False
        if getattr(best_match, "exclude_from_pnl", False):
            best_match.exclude_from_pnl = False
        paired_credit_ids.add(best_match.id)
        pairs_created += 1

    return pairs_created


async def unlink_transfer_pair(
    session: AsyncSession,
    workspace_id: uuid.UUID,
    pair_id: uuid.UUID,
) -> int:
    """Remove a transfer pair link. Returns number of transactions unlinked."""
    result = await session.execute(
        select(Transaction).where(
            Transaction.workspace_id == workspace_id,
            Transaction.transfer_pair_id == pair_id,
        )
    )
    transactions = list(result.scalars().all())

    for tx in transactions:
        tx.transfer_pair_id = None

    return len(transactions)
