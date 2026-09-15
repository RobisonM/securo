# Brazilian import fixtures (synthetic)

All files under this directory are **synthetic / anonymized**.

Do **not** commit real bank exports.

Forbidden in fixtures:

- real CPF / CNPJ
- real person or company names from private statements
- real account / agency numbers
- real FITIDs from a user's file

Institution names in filenames are illustrative of format shape only
(e.g. checking OFX SGML). Prefer `bank_*` / `credit_card_*` generics.

FITID values use the prefix `BRTEST-` (not `SYNTH-`). The OFX parser
discards `external_id` values starting with `SYNTH-` because those are
generated internally when a bank omits FITID.
