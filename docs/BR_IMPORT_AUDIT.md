# Auditoria do pipeline de importação brasileiro — Epic 4A

**Escopo:** análise + fixtures sintéticas + testes de caracterização.  
**Não inclui:** correções no importador, parsers novos, fingerprint, migrations, frontend, PDF, IA, Open Finance.

**Data:** 2026-09-15  
**Baseline de regressão alvo:** 3912 passed / 7 skipped / 1 failed (`test_invoice_document` SIGALRM no Windows).

---

## 1. Pipeline real de importação

Fluxo observado no código (`backend/app/api/import_transactions.py` + `import_service.py`):

```
arquivo (UploadFile)
  → detecção por extensão (.ofx/.qfx/.csv/.qif/.xml/.camt)
  → parser (parse_ofx | parse_csv | parse_qif | parse_camt)
  → [CSV] opções: date_format, flip_amount, inflow/outflow, column_mapping
  → preview HTTP: lista TransactionImport + sugestões de categoria por RULES
       (histórico Epic 3 NÃO roda no preview de import; rules sim)
  → cliente envia JSON TransactionImportRequest
  → import_transactions(...)
       → ImportLog
       → dedup (FITID+date OU fallback account/date/amount/type/description)
       → Transaction (original_description = description do parse)
       → apply_effective_date (cartão)
       → preview_rules_for_transaction / apply rules
       → recurring placeholder match
       → se imported > 0: transfer_detection_service
  → transaction final (category_id só via rules/CSV/user; suggestion histórica = API aparte)
```

Pontos críticos:

| Etapa | Comportamento atual |
|-------|---------------------|
| Preview | Parseia o arquivo no servidor |
| Import final | **Confia no JSON do cliente** (não re-parseia o arquivo) |
| Dedup OFX/QFX/QIF/CAMT | Sempre ligado |
| Dedup CSV | Controlado por `detect_duplicates` (default típico: on) |
| Transfer detection | Pós-import quando `imported > 0` |
| Category suggestion (Epic 3) | **Fora** do caminho de import; API de suggestion sob demanda |
| PIX/TED genéricos → transfer | Removidos do pack BR (Epics 1/2B); pairing só via transfer detection |

---

## 2. Formatos suportados

| Formato | Parser | Encoding | Status BR |
|---------|--------|----------|-----------|
| OFX SGML | `parse_ofx` (ofxparse) | UTF-8 → fallback Latin-1 | **PASS** nos cenários sintéticos |
| OFX XML / QFX | mesmo `parse_ofx` | idem | **PASS** (mesmo caminho) |
| CSV | `parse_csv` | **somente** `utf-8-sig` | **PARTIAL** (cp1252 FAIL) |
| QIF | `parse_qif` | utf-8-sig → latin-1 | **PARTIAL** (pouco usado BR; datas US-first por default) |
| CAMT.052/053 | `parse_camt` | XML bytes | **NOT SUPPORTED** como fluxo BR típico (EU) |

### 2.1 Campos por formato

#### OFX / QFX

| Campo | Fonte | Normalização |
|-------|--------|--------------|
| date | `DTPOSTED` via ofxparse → `txn.date` | só `date` (sem posting/purchase separados no parse) |
| amount | `TRNAMT` | `abs(Decimal)`; sinal → type |
| type | sinal de `TRNAMT` | `credit` se > 0, `debit` se ≤ 0 |
| external_id | FITID (`txn.id`) | descartado se prefixo `SYNTH-` |
| description | `MEMO` ou `PAYEE` | balance-summary rows filtradas |
| payee_raw | `PAYEE` | opcional |
| currency | header `CURDEF` não persistido por txn no parse | conta define na import |
| account id | `BANKACCTFROM` | **não** mapeado automaticamente à Account Securo |

**Dedup:** `(account_id, external_id, date)` quando há FITID.

#### CSV

| Campo | Auto-detect (EN/PT) | Notas |
|-------|---------------------|-------|
| date | date, data, dt, … | formatos: YYYY-MM-DD, DD/MM/YYYY, DD-MM-YYYY, MM/DD/YYYY, DD.MM.YYYY (+ override) |
| description | description, descricao, historico, … | |
| amount | amount, valor, … | `normalize_amount` (R$, 1.234,56, …) |
| type | type/tipo **ou** sinal do amount | positivo → credit; negativo → debit; depois `abs` |
| inflow/outflow | split columns | amounts positivos por coluna |
| external_id | **só** via `column_mapping` | auto-detect vazio |
| flip_amount | flag | inverte sinal antes de type |

**Dedup fallback:** `(account_id, date, amount, type, description|original_description)`.

#### QIF

| Campo | Tag |
|-------|-----|
| date | `D` |
| amount | `T` (vírgula US removida; **sem** `normalize_amount` BR) |
| payee / memo | `P` / `M` |
| external_id | nenhum |

#### CAMT

| Campo | Path típico |
|-------|-------------|
| amount / CdtDbtInd | `Amt` + crédito/débito |
| date | `BookgDt` / `ValDt` |
| description | `NtryDtls` / `AddtlNtryInf` |
| external_id | `AcctSvcrRef` / `TxId` quando presentes |
| status | só `BOOK` (PDNG ignorado) |

---

## 3. Matriz OFX Brasil (sintético)

| Cenário | Status | Risco | Teste | Correção necessária |
|---------|--------|-------|-------|---------------------|
| PIX saída DEBIT −80 | PASS | — | `test_ofx_pix_out_in_ted_tarifa_rendimento` | Nenhuma agora |
| PIX entrada CREDIT +2500 (não vira transfer sozinho) | PASS | — | idem + transfer tests | Nenhuma |
| TED recebida | PASS | — | idem | Nenhuma |
| Tarifa bancária | PASS | — | idem | Nenhuma |
| Rendimento / juros | PASS | — | idem | Nenhuma |
| Acentos Latin-1 / CHARSET 1252 | PARTIAL | P1 | `test_ofx_accent_latin1_sgml_current_behavior` | Documentar edge UTF-8 vs Latin-1; sem mudança 4A |
| Idempotência FITID | PASS | — | `test_ofx_import_idempotent_by_fitid` | Nenhuma |
| FITID mesmo em contas diferentes | PASS | — | `test_fitid_same_on_different_accounts_not_duplicate` | Nenhuma |
| Mesmo FITID, datas diferentes (parcelas) | PASS | — | `test_fitid_same_different_dates_are_distinct_installments` | Nenhuma |
| FITID vazio → SYNTH descartado | PASS (by design) | P1 | código `startswith("SYNTH-")` | Dedup cai no fallback (risco HIGH se 2 compras iguais) |

Fixtures: `backend/tests/fixtures/br/bank_checking_synth.ofx`, `bank_own_transfer_and_noise.ofx`, `bank_card_payment.ofx`.

---

## 4. Matriz CSV Brasil

| Cenário | Status | Risco | Teste | Correção necessária |
|---------|--------|-------|-------|---------------------|
| Delimitador `;` | PASS | — | `test_semicolon_brl_amounts` | Nenhuma |
| `1.234,56` / `R$` / negativo | PASS | — | `test_normalize_amount_matrix` | Nenhuma |
| Datas `DD/MM/YYYY` com `date_format` | PASS | — | semicolon fixture | Nenhuma |
| UTF-8 / UTF-8 BOM | PASS | — | `test_csv_utf8_bom_ok` | Nenhuma |
| Windows-1252 | FAIL | **P1** | `test_current_behavior_csv_utf8_only_for_cp1252` | Fallback latin-1/cp1252 (Epic futuro) |
| Amount positivo sem type → credit | PASS (atual) | **P1** em cartão | `test_current_behavior_positive_cc_csv_without_flip_is_credit` | UX preset / flip default para CC |
| `flip_amount=True` → debit | PASS | — | idem | Nenhuma |
| Split inflow/outflow | PASS (código) | P2 | testes legados existentes | Presets BR |
| external_id no CSV | PARTIAL | P2 | — | Exige column_mapping explícito |

Fixture: `br_semicolon.csv`, CSVs de cartão.

---

## 5. Cartão de crédito

| Cenário | Status | Risco | Notas |
|---------|--------|-------|-------|
| Compras CSV com amounts negativos → debit | PASS | — | `credit_card_purchases.csv` total 805.90 |
| Conta `type=credit_card` | PASS | — | type da txn é debit/credit do arquivo, não “expense” |
| Classification expense | PASS | — | derivada (Epic 2) quando categorizada e não transfer |
| `effective_date` preenchido no import | PASS | P2 | `apply_effective_date`; sem ciclo CC configurado ≈ `date` |
| Campos installment_* no arquivo CSV/OFX | NOT SUPPORTED | P2 | só via providers (ex. Pluggy); import arquivo não popula |

---

## 6. Parcelamento

| Cenário | Status | Risco | Teste |
|---------|--------|-------|-------|
| Mesmo FITID, datas distintas | PASS | — | `test_fitid_same_different_dates_are_distinct_installments` |
| CSV 01/10…03/10 sem FITID, datas distintas | PASS | — | `test_csv_installments_different_dates_no_fitid_remain_distinct` |
| Sem FITID, **mesma** data/amount/desc | FAIL (colapsa) | **P0** | `test_current_behavior_fallback_dedup_collapses_same_day_same_amount` |

**Risco HIGH** no fallback sem FITID para duas compras legítimas idênticas no mesmo dia.

---

## 7. Estorno

| Esperado | Status | Teste |
|----------|--------|-------|
| Compra debit + estorno credit persistem | PASS | `test_refund_persists_and_is_not_transfer` |
| Não viram transfer automaticamente | PASS | idem |
| Não eliminados por dedup (tipos opostos) | PASS | idem |
| Sem tipo `refund` | PASS (by design Epic 4A) | — |
| Classification | debit→expense / credit→income (se não transfer) | Epic 2 semantics |

---

## 8. Datas

| Conceito | Campo Securo | Import arquivo |
|----------|--------------|----------------|
| Data da transação / lançamento do extrato | `Transaction.date` | OFX `DTPOSTED`; CSV coluna date |
| Data efetiva (fluxo / fatura CC) | `Transaction.effective_date` | `apply_effective_date(account)` |
| Data de compra vs lançamento (cartão) | `installment_purchase_date` / bill | **não** vem do CSV/OFX de arquivo |
| Data de importação | `ImportLog` / `created_at` | não é `Transaction.date` |

**Comportamento atual (não alterado):** uma única data no parse; compra 31/08 vs lançamento 01/09 **não** são modeladas separadamente no import de arquivo. Relatórios cash vs accrual usam `date` vs `effective_date` conforme modo do dashboard.

---

## 9. Sinais

| Origem | Semântica |
|--------|-----------|
| OFX `TRNAMT` | sinal do banco → type; amount sempre positivo persistido |
| CSV amount assinado | `>0` credit, `<0` debit (salvo type explícito / split / flip) |
| CSV cartão “valor sempre positivo” | **vira credit** sem `flip_amount` ou type — gap P1 |
| Nunca assumir | `negative == expense` sem olhar `account.type` + classification |

`credit_card` + compra = tipicamente **debit** no ledger Securo; pagamento de fatura no cartão = **credit**.

---

## 10. Encoding

| Parser | UTF-8 | UTF-8 BOM | Latin-1 / cp1252 |
|--------|-------|-----------|------------------|
| OFX | sim | N/A (SGML) | fallback latin-1 após UTF-8 fail |
| CSV | sim | sim (`utf-8-sig`) | **UnicodeDecodeError** |
| QIF | sim | sim | fallback latin-1 |

---

## 11. Idempotência

| Formato | Com FITID estável | Sem ID |
|--------|-------------------|--------|
| OFX 2× | imported=0, skipped=N | fallback description |
| CSV 2× (detect on) | se external_id mapeado | fallback; risco colapso / miss |

Teste: `test_ofx_import_idempotent_by_fitid`.

---

## 12. FITID

| Caso | Resultado |
|------|-----------|
| Mesmo FITID + mesma data + mesma conta | duplicate (skip) |
| Mesmo FITID + contas diferentes | **não** duplicate |
| FITIDs diferentes | distinct |
| Mesmo FITID + datas diferentes | **distinct** (suporta parcelas BR) |

Prefixo `SYNTH-` no FITID **não** é persistido (IDs sintéticos do parser quando o banco omite FITID).

---

## 13. Fallback sem FITID

Chave: `account + date + amount + type + (description OR original_description)`.

| Caso | Comportamento | Risco |
|------|---------------|-------|
| Reimport mesma linha CSV | skip | LOW (desejado) |
| Duas compras SUPERMERCADO 100 mesmo dia | **1 importada, 1 skipped** | **HIGH / P0** |
| CSV `detect_duplicates=False` | permite duplicatas | P2 (opt-in) |

---

## 14. Duplicidade cross-format

| Sequência | Resultado atual |
|-----------|-----------------|
| OFX (FITID) depois CSV **mesma** desc/date/amount/type sem FITID | fallback **reconhece** → skip |
| OFX depois CSV com desc ligeiramente diferente | **duplica** |
| Sem fingerprint cross-format | documentado; não implementar no 4A |

Teste: `test_current_behavior_cross_format_ofx_then_csv_duplicates`  
Risco: **P1** (comum se CSV export truncar memo / adicionar sufixo).

---

## 15. Preview vs import

| Aspecto | Status |
|---------|--------|
| Mesmo parser na preview e (se cliente reenviar rows intactas) no persist | PASS para campos amount/type/date/description |
| Import **não** re-lê o arquivo | risco se UI alterar rows | **P1** se cliente mutar |
| Rules: preview enriquece sugestões; import aplica rules de fato | alinhado via `preview_rules_for_transaction` |
| Sugestão histórica Epic 3 | **não** no preview de arquivo | P2 UX |

Teste: `test_preview_parse_matches_import_amounts_and_types` (parse → persist, mesmos campos).

---

## 16. Transfer detection (pipeline real)

| Cenário | Status | Teste |
|---------|--------|-------|
| PIX própria conta debit + credit (contas distintas, match) | PASS | `test_own_account_transfer_pairs_uber_does_not` |
| UBER debit + DEPÓSITO credit mesmo valor | PASS (não paira) | idem |
| Pagamento fatura bank debit + card credit | PASS → `card_payment` | `test_card_bill_payment_pairs_through_import_pipeline` |
| PIX genérico sozinho → transfer | PASS (não) | Epics 1/2B |

P&L pagamento cartão: um par `card_payment` — **não** 2× a despesa (805, não 1610).

---

## 17. Category suggestion (pós-import)

| Esperado | Status | Teste |
|----------|--------|-------|
| Import deixa `category_id=NULL` (sem rule) | PASS | `test_import_leaves_uncategorized_and_suggestion_available` |
| Suggestion API preenche suggestion, **não** grava category | PASS | idem |
| Consenso histórico Epic 3 | PASS | IFOOD → Alimentação |

---

## 18. Gaps P0

1. **Fallback dedup colapsa duas compras legítimas** (mesmo dia/amount/desc, sem FITID) — valor financeiro incompleto.  
2. *(Mitigado nos Epics 1–2)* Pagamento de cartão / transfer falso positivo por rules PIX — revalidado PASS no pipeline.

Nenhum P0 de **sinal invertido OFX** encontrado nos fixtures sintéticos com TRNAMT bancário padrão.

---

## 19. Gaps P1

1. CSV **Windows-1252** não parseia.  
2. CSV cartão com valores **sempre positivos** → credit sem `flip_amount`.  
3. Cross-format OFX→CSV com memo divergente → **duplicata**.  
4. Import final confia no JSON do cliente (preview ≠ re-parse).  
5. OFX sem FITID real → SYNTH descartado → cai no fallback HIGH.

---

## 20. Gaps P2 / P3

| Gap | Prioridade |
|-----|------------|
| Presets de banco/cartão BR (colunas, flip, date_format) | P2 |
| Popular installment_* / purchase vs posting no import arquivo | P2 |
| external_id auto no CSV BR | P2 |
| QIF amount sem normalize BR | P3 |
| CAMT no fluxo BR | P3 / N/A |
| Encoding OFX edge cases mistos | P3 |
| Fingerprint estável cross-format | P2 (Epic futuro) |

---

## 21. Testes adicionados

Arquivo: `backend/tests/test_br_import_characterization.py`

Cobertura: parse OFX/CSV, encoding, sinais CC, idempotência FITID, parcelas, fallback HIGH, card payment pipeline, transfer vs noise, estorno, cross-format, preview↔persist, suggestion pós-import, effective_date CC.

Nomes `test_current_behavior_*` documentam gaps sem forçar correção.

---

## 22. Fixtures

Diretório: `backend/tests/fixtures/br/`

| Arquivo | Uso |
|---------|-----|
| `bank_checking_synth.ofx` | PIX/TED/tarifa/rendimento |
| `bank_own_transfer_and_noise.ofx` | transfer + UBER/depósito |
| `bank_card_payment.ofx` | pagamento fatura (banco) |
| `credit_card_purchases.csv` | compras |
| `credit_card_payment.csv` | crédito fatura |
| `credit_card_installments.csv` | parcelas |
| `credit_card_refund.csv` | estorno |
| `br_semicolon.csv` | `;` + R$ + dd/mm |
| `README.md` | regras de anonimização |

Todos sintéticos; FITIDs `BRTEST-*`.

---

## 23. Respostas às 14 perguntas do Epic

1. **OFX BR** — sim nos cenários sintéticos cobertos (PASS).  
2. **CSV configurável** — parcialmente (mapeamento/flip/date_format sim; cp1252 não).  
3. **Cartão** — purchases como debit OK se sinal/flip corretos; classification OK.  
4. **Reimport idempotente** — sim com FITID; fallback sem FITID frágil.  
5. **Parcelas** — distintas se datas (ou FITID+date) diferem.  
6. **Datas** — uma data de extrato; effective_date separado no CC.  
7. **Valores/sinais** — OFX OK; CSV positivo→credit é armadilha.  
8. **Pagamento fatura** — pair + `card_payment` no pipeline.  
9. **Estornos** — persistem; não transfer; sem tipo refund.  
10. **PIX/TED** — não viram transfer só por texto.  
11. **Encoding pt-BR** — OFX latin-1 ok; CSV cp1252 fail.  
12. **Formatos monetários BR** — `normalize_amount` OK no CSV.  
13. **Duplicidade entre formatos** — parcial; memo diverge → duplica.  
14. **Preview = import** — se rows intactas sim; arquitetura JSON-trust é gap.

---

## 24–27. Regressão / migrations

| Métrica | Baseline | Após Epic 4A |
|---------|----------|--------------|
| passed | 3912 | **3932** (+20 caracterização) |
| skipped | 7 | 7 |
| failed | 1 | 1 (`test_invoice_document` SIGALRM Windows — preexistente) |
| Novas regressões | — | **ZERO** |
| Migrations | — | **NENHUMA** |
| Correções no importador | — | **NENHUMA** |

---

## Epic 4B — correções (2026-09-15)

| Gap 4A | Correção | Migration |
|--------|----------|-----------|
| P0 fallback colapsa 2 compras | Contagem de ocorrência no soft-dedup + `IMP-{file_fp}:{row}` sem FITID | Nenhuma |
| Reimport idempotente | Mesmos `IMP-*` / FITID → skip | Nenhuma |
| CSV cp1252 | `decode_csv_text`: utf-8-sig → utf-8 → cp1252 | Nenhuma |
| CC positivo → credit silencioso | `amount_semantics` se credit_card e só credits | Nenhuma |
| Preview ≠ import | `import_mac` HMAC dos campos imutáveis | Nenhuma |
| Cross-format memo diverge | Sem fuzzy; exact soft-match OK | Nenhuma |

FITID bancário real inalterado. Monetário BR / datas DD/MM preservados; `DD-MM-YYYY` no mapa explícito.
