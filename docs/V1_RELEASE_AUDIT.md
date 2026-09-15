# Securo Brasil V1 — Release Audit (Epic 5C)

**Data:** 2026-09-15  
**Branch:** `feature/finance-br`  
**Escopo:** release gate / estabilização. Sem features novas. Sem migrations.

---

## 1. Status V1

| Critério | Resultado |
|----------|-----------|
| P0 abertos neste gate | **ZERO** |
| Vazamento entre workspaces | **Não encontrado** (testes de isolamento em dashboard + suggestions) |
| Inconsistência financeira conhecida no fluxo V1 | **Nenhuma** (cenário de referência coberto) |
| Fixtures bancárias reais | **Nenhuma** (somente sintéticas) |
| Migrations novas nos Epics 1–5 | **Nenhuma** |
| Novas regressões vs baseline | **ZERO** (falha permitida: SIGALRM Windows) |
| typecheck / build / i18n parity | **OK** |

**Recomendação: GO** para uso pessoal V1 (pré–Open Finance), com limitações documentadas abaixo.

---

## 2. Arquitetura final (Epics 1–5)

```
Import (OFX/CSV)
  → normalização / amount_semantics / import_mac
  → dedup (FITID ou IMP-{sha16}:{row})
  → transfer / card_payment detection
  → persistência Transaction
  → classification derivada (não persistida como fonte de verdade)
  → category suggestion (histórico; nunca auto-apply)
  → dashboard agrega via counts_as_user_pnl()
```

**Backend:** FastAPI + SQLAlchemy + Alembic + PostgreSQL.  
**Frontend:** React + TypeScript + TanStack Query + Recharts.  
**Regra de ouro:** lógica financeira nos services; routers finos; FE não recalcula P&L.

---

## 3. Features V1

| Epic | Entrega |
|------|---------|
| 1 | Integridade financeira / P&L (`counts_as_user_pnl`) |
| 2A/2B | Classification derivada + API |
| 2C | Pending categorization inbox |
| 3A | Category suggestions históricas |
| 3B | Merchant identity (`merchant_key` em memória/API) |
| 4A | Auditoria de import BR (fixtures + characterization) |
| 4B | Fixes import BR (dedup, encoding, amount_semantics, MAC) |
| 5A | Dashboard financial truth (summary net, trend, tops, cards) |
| 5B | Dashboard visual pessoal (widgets + período + empty/error) |

---

## 4. Invariantes financeiros

1. Transferências paired **não** são despesa/receita.
2. Pagamento de fatura paired (`card_payment`) **não** duplica compras.
3. Compras no cartão **são** despesa.
4. Uncategorized **entra** em expense e em pending.
5. `exclude_from_pnl` / `is_ignored` / opening_balance / settlement fora do P&L.
6. Import idempotente: reimportar o mesmo arquivo não multiplica linhas.
7. Suggestions **nunca** auto-aplicam categoria.
8. Aceitar suggestion **não** cria Rule; Rule exige ação explícita + preview.
9. Dashboard FE consome agregados da API; não filtra P&L por `transfer_pair_id` / etc.

### Cenário de referência (testado)

| Conceito | Valor |
|----------|-------|
| income | 8.000 |
| expense (categorizado) | 2.155 |
| expense + “Loja desconhecida” | 2.255 |
| net (base) | 5.845 |
| pending count / amount | 1 / 100 |
| card purchases + payment 2.155 | expense = 2.155 (**não** 4.310) |
| own transfer 2.000 | P&L inalterado |

Cobertura: `test_personal_dashboard_metrics.py`, `test_financial_integrity_p0.py`, `test_br_import_fixes.py`.

---

## 5. Limitações conhecidas (não viram feature neste Epic)

| # | Limitação | Severidade |
|---|-----------|------------|
| L1 | Cross-format dedup com memo diferente pode duplicar | P1 |
| L2 | `import_mac` opcional (clientes legados sem MAC) | P1 / compat |
| L3 | Top merchants do dashboard não agrega por `merchant_key` SQL | P2 |
| L4 | `CreditCardBill` sem `closing_date` dedicado | P2 |
| L5 | Schemas dashboard ainda serializam `float` na borda (cálculo interno Decimal) | P2 |
| L6 | `test_invoice_document` SIGALRM no Windows | pré-existente |
| L7 | Merchant model persistido / Open Finance / orçamentos avançados | fora de V1 |

---

## 6. P0 / P1 / P2 restantes

### P0
- **Nenhum** bloqueador aberto neste gate.

### P1 (follow-up pós-V1)
- Dedup cross-format (OFX vs CSV) quando memo diverge.
- Endurecer política `import_mac` quando todos os clientes forem atualizados.
- Cobertura E2E manual em mobile real (inbox + dashboard) além dos testes unitários.

### P2
- Agregar top merchants por `merchant_key`.
- `closing_date` em bill quando modelo permitir.
- Migrar borda JSON de dashboard de `float` → string Decimal (breaking controlado).
- Corrigir/adaptar teste SIGALRM invoice no Windows.

---

## 7. Test coverage relevante

| Área | Arquivos |
|------|----------|
| Integrity / transfers / card | `test_financial_integrity_p0.py` |
| BR import fixes | `test_br_import_fixes.py`, fixtures `tests/fixtures/br/` |
| Characterization | `test_br_import_characterization.py` |
| Classification | `test_transaction_classification*.py` |
| Suggestions | `test_category_suggestion.py` |
| Merchant identity | `test_merchant_identity.py` |
| Dashboard metrics | `test_personal_dashboard_metrics.py` |
| FE pending / dashboard | `pending-*.test.tsx`, `dashboard-widgets.test.tsx` |
| i18n | `locales/i18n.test.ts` (15 locales) |

---

## 8. Migrations

- Alembic head: **089**
- Diff em `backend/alembic/`: **vazio**
- Epics 1–5: **nenhuma migration criada**

---

## 9. Segurança / privacy

- Fixtures BR: sintéticas (`BRTEST-*`, `ACCT-*-SYNTH-*`); README proíbe dados reais.
- Services novos dos Epics: sem logs de descrição bancária / CPF / CNPJ / raw statement.
- Isolamento de workspace coberto em dashboard e category suggestions.
- Dashboard FE: `reduce`/`filter` restantes são agregação de **saldos de contas** e UI — não P&L de transações.

---

## 10. Performance sanity

| Área | Decisão V1 |
|------|------------|
| Suggestions | ≤2 history queries por página (batch; testado) |
| Dashboard | Agregações SQL (`SUM`/`GROUP BY`/`LIMIT`) |
| Classification | Derivada em batch na listagem |
| Import | Sem carregar statement inteiro para P&L no FE |

Sem N+1 por item introduzido nos Epics 3A/5A observado nos testes de bound.

---

## 11. Dependências

- Nenhuma biblioteca grande adicionada nos Epics 1–5.
- `frontend/package-lock.json`: apenas metadados `dev`/`devOptional` (ruído npm) — **sem nova dep de produto**.

---

## 12. TODO / FIXME nos arquivos dos Epics

Busca em services/FE dashboard dos Epics: **nenhum TODO/FIXME/HACK/XXX blocker**.

---

## 13. Falha conhecida

```
FAILED tests/test_invoice_document.py::test_a_line_taller_than_a_page_still_finishes
AttributeError: module 'signal' has no attribute 'SIGALRM'  # Windows
```

Pré-existente; fora do escopo financeiro BR V1.

---

## 14. Próximos passos (após GO)

1. Commit único (ou série pequena) dos artefatos Epics 1–5 — ver lista no relatório 5C.
2. Uso pessoal real em workspace isolado.
3. Open Finance **somente depois** de estabilizar V1 em produção pessoal.
4. Backlog P1/P2 acima — sem misturar com Open Finance no mesmo Epic.

---

## 15. O que NÃO entra no commit (higiene)

- `backend/data/attachments/**` e qualquer extrato real (se aparecer no working tree).
- Cache `__pycache__` / `.pytest_cache`.
- Não commitar secrets `.env`.
