"""Unit tests for description signature extraction (Epic 3A)."""

from app.services.description_signature import (
    description_matches_signature,
    extract_stable_description_term,
)


def test_extracts_ifood_from_pix_qr_clutter():
    assert extract_stable_description_term("PIX QR CODE IFOOD 123456789") == "IFOOD"


def test_extracts_netflix():
    assert extract_stable_description_term("NETFLIX.COM") == "NETFLIX"


def test_rejects_generic_pix_to_person():
    assert extract_stable_description_term("PIX ENVIADO JOAO") is None


def test_rejects_noise_only():
    assert extract_stable_description_term("PIX QR CODE") is None
    assert extract_stable_description_term("") is None


def test_prefers_longest_merchant_token():
    assert extract_stable_description_term("PAGAMENTO MERCADOLIVRE 998877") == "MERCADOLIVRE"


def test_description_matches_signature():
    assert description_matches_signature("IFOOD *8472", "IFOOD")
    assert not description_matches_signature("UBER TRIP", "IFOOD")
