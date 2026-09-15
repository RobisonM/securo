"""Epic 3B — merchant identity matrix (tests written before algorithm changes).

These cases define the intended derive_merchant_key behaviour for BR bank memos.
"""

from __future__ import annotations

import pytest

from app.services.description_signature import derive_merchant_key


# ---------------------------------------------------------------------------
# Same merchant — variants must collapse
# ---------------------------------------------------------------------------

IFOOD_VARIANTS = [
    "IFOOD",
    "IFOOD *123456",
    "PIX QR CODE IFOOD 847362",
    "PGTO IFOOD",
    "COMPRA IFOOD SA",
]

NETFLIX_VARIANTS = [
    "NETFLIX.COM",
    "NETFLIX 1234",
    "PAGAMENTO NETFLIX",
]

UBER_VARIANTS = [
    "UBER *TRIP",
    "UBER DO BRASIL",
    "UBER 829173",
]

SHELL_VARIANTS = [
    "POSTO SHELL",
    "AUTO POSTO SHELL LTDA",
]

COMPER_VARIANTS = [
    "SUPERMERCADO COMPER",
    "PIX PAGAMENTO COMPER",
]

MERCADO_LIVRE_VARIANTS = [
    "MERCADO LIVRE",
    "MERCADOLIVRE",
    "MP *MERCADOLIVRE",
]

AMAZON_VARIANTS = [
    "AMAZON",
    "AMZN",
    "AMAZON BR",
]


@pytest.mark.parametrize("memo", IFOOD_VARIANTS)
def test_ifood_variants_share_key(memo: str):
    assert derive_merchant_key(memo) == "IFOOD"


@pytest.mark.parametrize("memo", NETFLIX_VARIANTS)
def test_netflix_variants_share_key(memo: str):
    assert derive_merchant_key(memo) == "NETFLIX"


@pytest.mark.parametrize("memo", UBER_VARIANTS)
def test_uber_variants_share_key(memo: str):
    assert derive_merchant_key(memo) == "UBER"


@pytest.mark.parametrize("memo", SHELL_VARIANTS)
def test_shell_variants_share_key(memo: str):
    assert derive_merchant_key(memo) == "SHELL"


@pytest.mark.parametrize("memo", COMPER_VARIANTS)
def test_comper_variants_share_key(memo: str):
    assert derive_merchant_key(memo) == "COMPER"


@pytest.mark.parametrize("memo", MERCADO_LIVRE_VARIANTS)
def test_mercado_livre_variants_share_key(memo: str):
    assert derive_merchant_key(memo) == "MERCADO LIVRE"


@pytest.mark.parametrize("memo", AMAZON_VARIANTS)
def test_amazon_variants_share_key(memo: str):
    assert derive_merchant_key(memo) == "AMAZON"


# ---------------------------------------------------------------------------
# Must NOT collide
# ---------------------------------------------------------------------------

def test_posto_sao_jose_vs_supermercado_sao_jose_do_not_collide():
    a = derive_merchant_key("POSTO SAO JOSE")
    b = derive_merchant_key("SUPERMERCADO SAO JOSE")
    assert a is not None and b is not None
    assert a != b


def test_joao_silva_vs_maria_silva_not_merchants_or_distinct():
    # Person-style PIX must not become a merchant identity.
    assert derive_merchant_key("PIX ENVIADO JOAO SILVA") is None
    assert derive_merchant_key("PIX RECEBIDO MARIA SILVA") is None


def test_padaria_central_vs_farmacia_central_do_not_collide():
    a = derive_merchant_key("PADARIA CENTRAL")
    b = derive_merchant_key("FARMACIA CENTRAL")
    assert a is not None and b is not None
    assert a != b


def test_banco_do_brasil_vs_bb_seguridade_do_not_collide():
    a = derive_merchant_key("BANCO DO BRASIL")
    b = derive_merchant_key("BB SEGURIDADE")
    assert a is not None and b is not None
    assert a != b


# ---------------------------------------------------------------------------
# Generics / unsafe
# ---------------------------------------------------------------------------

@pytest.mark.parametrize(
    "memo",
    [
        "TED RECEBIDA",
        "PIX QR CODE",
        "PAGAMENTO",
        "TRANSFERENCIA",
        "",
        None,
    ],
)
def test_generic_memos_have_no_merchant_key(memo: str | None):
    assert derive_merchant_key(memo) is None


def test_extract_stable_term_still_available_for_fallback():
    from app.services.description_signature import extract_stable_description_term

    assert extract_stable_description_term("IFOOD *1") == "IFOOD"
