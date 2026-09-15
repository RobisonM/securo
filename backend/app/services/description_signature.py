"""Stable merchant identity for Brazilian bank memos (Epics 3A / 3B).

Computed in memory only — never persisted. The TypeScript helper in the
frontend (`similar-description.ts`) is for rule-draft UX; this module is the
source of truth for historical category suggestions.

Epic 3B adds ``derive_merchant_key`` — a canonical identity used for history
matching. It is NOT a Payee and is NOT stored.

Noise / stopwords alone never identify a counterparty.
A small explicit BR alias map covers unequivocal variants only.
"""

from __future__ import annotations

import re
import unicodedata

# Financial / card rail stopwords — justified by merchant-matrix tests.
_NOISE_RAW = (
    "PIX",
    "TED",
    "DOC",
    "QR",
    "CODE",
    "PAGAMENTO",
    "PAGTO",
    "PGTO",
    "COMPRA",
    "DEBITO",
    "CREDITO",
    "CARTAO",
    "VISA",
    "MASTERCARD",
    "ELO",
    "TRANSF",
    "TRANSFER",
    "TRANSFERENCIA",
    "ENVIADO",
    "RECEBIDO",
    "ENVIO",
    "RECEBIMENTO",
    "RECEBIDA",
    "TARIFA",
    "TAXA",
    "IOF",
    "CDC",
    "CC",
    "CPF",
    "CNPJ",
    "NSU",
    "AUTH",
    "AUT",
    "REF",
    "ID",
    "PARCELA",
    "PARC",
    # Corporate / geographic fillers that are not merchants alone
    "LTDA",
    "EIRELI",
    "ME",
    "EPP",
    "SA",
    "S.A",
    "DO",
    "DA",
    "DE",
    "DOS",
    "DAS",
    "BR",
    # "BRASIL" kept as a candidate so "BANCO DO BRASIL" survives after DO drop
    "AUTO",  # "AUTO POSTO SHELL" → POSTO/SHELL
    "MP",  # Mercado Pago prefix on ML memos
    "TRIP",  # UBER *TRIP
)

# Tokens that are too weak to be a merchant_key by themselves (collision risk).
_WEAK_SOLO = frozenset(
    {
        "SAO",
        "JOSE",
        "MARIA",
        "JOAO",
        "SILVA",
        "CENTRAL",
        "POSTO",
        "SUPERMERCADO",
        "PADARIA",
        "FARMACIA",
        "BANCO",
        "SEGURIDADE",
    }
)

# Unequivocal BR aliases → canonical merchant_key (spaces allowed).
# Keep this list tiny and test-backed.
_BR_ALIASES: dict[str, str] = {
    "MERCADOLIVRE": "MERCADO LIVRE",
    "MERCADOLIBRE": "MERCADO LIVRE",
    "AMZN": "AMAZON",
    "AMAZONCOM": "AMAZON",
    "NETFLIXCOM": "NETFLIX",
}

# Well-known single-token brands: if present after filtering, they win.
_KNOWN_BRANDS = frozenset(
    {
        "IFOOD",
        "NETFLIX",
        "UBER",
        "SHELL",
        "COMPER",
        "AMAZON",
        "SPOTIFY",
        "GOOGLE",
        "APPLE",
        "MAGALU",
        "SHOPEE",
        "IUGU",
        "NUBANK",
    }
)


def _strip_accents(value: str) -> str:
    return "".join(
        ch
        for ch in unicodedata.normalize("NFKD", value)
        if not unicodedata.combining(ch)
    )


NOISE_TOKENS = {_strip_accents(t).upper().replace(".", "") for t in _NOISE_RAW}

_SPLIT_RE = re.compile(r"[\s*_/|\\,;:+\-]+")
_PIX_PERSON_RE = re.compile(r"\bPIX\s+(ENVIADO|RECEBIDO)\b", re.IGNORECASE)


def _is_mostly_digits(token: str) -> bool:
    digits = sum(1 for ch in token if ch.isdigit())
    return digits > 0 and digits >= len(token) * 0.5


def _normalize_token(raw: str) -> str:
    token = _strip_accents(raw).upper()
    token = re.sub(r"^[^A-Z0-9]+|[^A-Z0-9]+$", "", token)
    token = token.replace(".", "")
    if token.endswith("COM") and len(token) > 3:
        # NETFLIXCOM from NETFLIX.COM after dot strip — handled via alias too
        pass
    if token.endswith("COM") and token[:-3] in _KNOWN_BRANDS:
        token = token[:-3]
    if token.endswith("BR") and token[:-2] in _KNOWN_BRANDS:
        token = token[:-2]
    return token


def _candidate_tokens(description: str) -> list[str]:
    candidates: list[str] = []
    for part in _SPLIT_RE.split(description):
        token = _normalize_token(part)
        if not token:
            continue
        if len(token) < 2:
            continue
        if token in NOISE_TOKENS:
            continue
        if _is_mostly_digits(token):
            continue
        if token.isdigit():
            continue
        # Apply token-level aliases that expand to multi-word keys later
        aliased = _BR_ALIASES.get(token)
        if aliased and " " in aliased:
            candidates.extend(aliased.split())
            continue
        if aliased:
            candidates.append(aliased)
            continue
        candidates.append(token)
    return candidates


def derive_merchant_key(description: str | None) -> str | None:
    """Canonical merchant identity for history matching, or None when unsafe.

    Person-to-person PIX (ENVIADO/RECEBIDO) returns None — that is not a
    merchant identity. A separate counterparty_key is intentionally not
    exposed yet to avoid learning categories from personal names.
    """
    text = (description or "").strip()
    if not text:
        return None

    stripped = _strip_accents(text)
    if _PIX_PERSON_RE.search(stripped):
        return None

    tokens = _candidate_tokens(text)
    if not tokens:
        return None

    # Compact whole-memo alias (e.g. glued MERCADOLIVRE already handled per token)
    compact = "".join(tokens)
    if compact in _BR_ALIASES:
        return _BR_ALIASES[compact]

    # Known brand token present → that brand is the identity
    for brand in _KNOWN_BRANDS:
        if brand in tokens:
            return brand

    # Two-token compound when the first alone is weak/generic
    # e.g. POSTO SAO JOSE, PADARIA CENTRAL, BANCO DO BRASIL (DO already noise)
    if len(tokens) >= 2:
        # Prefer first + remaining weak/context tokens up to 3
        compound_parts = tokens[:3]
        compound = " ".join(compound_parts)
        # Avoid collapsing everything to a single weak token
        if compound_parts[0] in _WEAK_SOLO or len(compound_parts) > 1:
            return compound

    solo = tokens[0]
    if solo in _WEAK_SOLO:
        return None
    if len(solo) < 4:
        return None
    return solo


def extract_stable_description_term(description: str | None) -> str | None:
    """Legacy compact token (Epic 3A). Prefer ``derive_merchant_key`` for matching.

    Kept for fallback when merchant_key is unavailable and for rule-draft UX
    alignment. Uses the longest non-noise token of length >= 4.
    """
    text = (description or "").strip()
    if not text:
        return None

    stripped = _strip_accents(text)
    if _PIX_PERSON_RE.search(stripped):
        return None

    candidates: list[str] = []
    for part in _SPLIT_RE.split(text):
        token = _normalize_token(part)
        if not token:
            continue
        if len(token) < 4:
            continue
        if token in NOISE_TOKENS:
            continue
        if _is_mostly_digits(token):
            continue
        if token.isdigit():
            continue
        candidates.append(token)

    if not candidates:
        return None

    return max(candidates, key=len)


def description_matches_signature(description: str | None, signature: str) -> bool:
    """True when the memo contains the signature as a contiguous match."""
    if not signature:
        return False
    text = _strip_accents(description or "").upper().replace(".", "")
    sig = _strip_accents(signature).upper().replace(".", "")
    return sig in text


def description_matches_merchant_key(description: str | None, merchant_key: str) -> bool:
    """True when derive_merchant_key(description) equals the canonical key."""
    if not merchant_key:
        return False
    return derive_merchant_key(description) == merchant_key


def merchant_key_search_needles(merchant_key: str) -> list[str]:
    """Tokens suitable for SQL ILIKE prefiltering of a merchant_key."""
    key = merchant_key.strip().upper()
    if not key:
        return []
    parts = key.split()
    needles = {key.replace(" ", ""), parts[0]}
    if len(parts) > 1:
        needles.add(parts[-1])
    return [n for n in needles if len(n) >= 3]
