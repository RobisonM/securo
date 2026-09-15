"""Unit tests for derived transaction classification (no database)."""

from __future__ import annotations

import uuid

from app.services.transaction_classification import (
    ClassificationInput,
    classify_transaction,
    classify_transactions,
    counterpart_account_type_for,
    group_pair_legs,
    is_card_payment_pair,
)

CATEGORY = uuid.uuid4()
PAIR = uuid.uuid4()
ACC_BANK = uuid.uuid4()
ACC_CARD = uuid.uuid4()


def _classify(**kwargs) -> str:
    defaults = {
        "type": "debit",
        "account_type": "checking",
        "category_id": CATEGORY,
    }
    defaults.update(kwargs)
    return classify_transaction(ClassificationInput(**defaults))


# ---------------------------------------------------------------------------
# Ordinary income / expense / uncertain
# ---------------------------------------------------------------------------


def test_checking_credit_categorized_is_income():
    assert _classify(type="credit", account_type="checking") == "income"


def test_checking_debit_categorized_is_expense():
    assert _classify(type="debit", account_type="checking") == "expense"


def test_checking_debit_uncategorized_is_uncertain():
    assert _classify(type="debit", category_id=None) == "uncertain"


def test_checking_credit_uncategorized_is_uncertain():
    assert _classify(type="credit", category_id=None) == "uncertain"


# ---------------------------------------------------------------------------
# Adjustment
# ---------------------------------------------------------------------------


def test_exclude_from_pnl_is_adjustment():
    assert (
        _classify(type="debit", exclude_from_pnl=True, category_id=None)
        == "adjustment"
    )


def test_adjustment_beats_paired_transfer():
    """exclude_from_pnl wins even when a pair exists."""
    assert (
        _classify(
            type="debit",
            exclude_from_pnl=True,
            transfer_pair_id=PAIR,
            counterpart_account_type="savings",
        )
        == "adjustment"
    )


# ---------------------------------------------------------------------------
# Transfers & card payments
# ---------------------------------------------------------------------------


def test_checking_paired_with_savings_is_transfer_both_legs():
    debit = _classify(
        type="debit",
        account_type="checking",
        category_id=None,
        transfer_pair_id=PAIR,
        counterpart_account_type="savings",
    )
    credit = _classify(
        type="credit",
        account_type="savings",
        category_id=None,
        transfer_pair_id=PAIR,
        counterpart_account_type="checking",
    )
    assert debit == "transfer"
    assert credit == "transfer"


def test_checking_paired_with_credit_card_is_card_payment_both_legs():
    bank_leg = _classify(
        type="debit",
        account_type="checking",
        category_id=None,
        transfer_pair_id=PAIR,
        counterpart_account_type="credit_card",
    )
    card_leg = _classify(
        type="credit",
        account_type="credit_card",
        category_id=None,
        transfer_pair_id=PAIR,
        counterpart_account_type="checking",
    )
    assert bank_leg == "card_payment"
    assert card_leg == "card_payment"


def test_paired_without_counterpart_type_falls_back_to_transfer():
    """Missing counterpart context must not invent card_payment."""
    assert (
        _classify(
            type="debit",
            account_type="checking",
            category_id=None,
            transfer_pair_id=PAIR,
            counterpart_account_type=None,
        )
        == "transfer"
    )


def test_paired_uncategorized_is_not_uncertain():
    assert (
        _classify(
            type="debit",
            category_id=None,
            transfer_pair_id=PAIR,
            counterpart_account_type="savings",
        )
        == "transfer"
    )
    assert (
        _classify(
            type="debit",
            category_id=None,
            transfer_pair_id=PAIR,
            counterpart_account_type="credit_card",
        )
        == "card_payment"
    )


def test_treat_as_transfer_category_without_pair_is_transfer():
    assert (
        _classify(
            type="debit",
            category_id=CATEGORY,
            treat_as_transfer=True,
            transfer_pair_id=None,
        )
        == "transfer"
    )


def test_is_card_payment_pair_helper():
    assert is_card_payment_pair("checking", "credit_card")
    assert is_card_payment_pair("credit_card", "savings")
    assert not is_card_payment_pair("checking", "savings")
    assert not is_card_payment_pair("credit_card", "credit_card")
    assert not is_card_payment_pair("checking", None)


# ---------------------------------------------------------------------------
# Credit card purchases & refunds
# ---------------------------------------------------------------------------


def test_credit_card_purchase_categorized_is_expense():
    assert (
        _classify(type="debit", account_type="credit_card", category_id=CATEGORY)
        == "expense"
    )


def test_credit_card_refund_categorized_is_income():
    """Current semantics: a categorized card credit is income (not a dedicated
    refund type). Pairing / ignore / exclude_from_pnl can still reclassify.
    """
    assert (
        _classify(type="credit", account_type="credit_card", category_id=CATEGORY)
        == "income"
    )


# ---------------------------------------------------------------------------
# is_ignored — orthogonal to classification
# ---------------------------------------------------------------------------


def test_is_ignored_does_not_become_adjustment():
    assert (
        _classify(type="debit", is_ignored=True, category_id=CATEGORY) == "expense"
    )


def test_is_ignored_uncategorized_is_still_uncertain():
    assert _classify(type="debit", is_ignored=True, category_id=None) == "uncertain"


def test_is_ignored_with_exclude_from_pnl_is_adjustment():
    assert (
        _classify(type="debit", is_ignored=True, exclude_from_pnl=True) == "adjustment"
    )


def test_is_ignored_paired_transfer_still_transfer():
    assert (
        _classify(
            type="debit",
            is_ignored=True,
            category_id=None,
            transfer_pair_id=PAIR,
            counterpart_account_type="savings",
        )
        == "transfer"
    )


# ---------------------------------------------------------------------------
# Batch helpers (N+1 avoidance)
# ---------------------------------------------------------------------------


def test_classify_transactions_batch():
    rows = [
        ClassificationInput(type="credit", account_type="checking", category_id=CATEGORY),
        ClassificationInput(type="debit", account_type="checking", category_id=None),
    ]
    assert classify_transactions(rows) == ["income", "uncertain"]


def test_group_pair_legs_and_counterpart_lookup():
    pair = uuid.uuid4()
    legs = group_pair_legs(
        [
            (pair, ACC_BANK, "checking"),
            (pair, ACC_CARD, "credit_card"),
        ]
    )
    assert (
        counterpart_account_type_for(
            transfer_pair_id=pair, account_id=ACC_BANK, pair_legs=legs
        )
        == "credit_card"
    )
    assert (
        counterpart_account_type_for(
            transfer_pair_id=pair, account_id=ACC_CARD, pair_legs=legs
        )
        == "checking"
    )
