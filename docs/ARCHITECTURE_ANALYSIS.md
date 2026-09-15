# Análise de Arquitetura — Securo

Documento de referência para adaptação do Securo a um sistema de gestão financeira pessoal focado no mercado brasileiro.

**Escopo desta análise:** somente leitura do código existente. Nenhuma alteração funcional foi feita.

**Data:** 2026-09-14

---

## 1. Arquitetura geral

Securo é uma aplicação de finanças pessoais **multi-tenant por workspace**, com:

| Camada | Stack |
|--------|--------|
| Backend | FastAPI + SQLAlchemy async + PostgreSQL + Alembic + Celery/Redis |
| Frontend | Vite + React 19 + TypeScript + TanStack Query + Axios + i18next + Tailwind/shadcn |
| Integrações | Open Finance (Pluggy — BR), SimpleFIN, Enable Banking; FX; Tesouro Direto (cache) |
| Domínio fiscal | Packs por jurisdição (`backend/app/fiscal/`), incluindo `br.toml` (CPF/CNPJ/IE/IM) |

### Visão em camadas

```
┌─────────────────────────────────────────────────────────────┐
│  Frontend (SPA)                                             │
│  pages/ + components/ → lib/api.ts → /api/*                 │
└────────────────────────────┬────────────────────────────────┘
                             │ Bearer + X-Workspace-Id
┌────────────────────────────▼────────────────────────────────┐
│  FastAPI (backend/app/main.py)                              │
│  api/* → services/* → models/* → PostgreSQL                 │
│  tasks/* (Celery) ← sync bancário, jobs                     │
└─────────────────────────────────────────────────────────────┘
```

### Multi-tenancy

- Quase todas as tabelas financeiras carregam `workspace_id` (CASCADE a partir de `workspaces`).
- Contexto injetado via `WorkspaceContext` / header `X-Workspace-Id` (`backend/app/core/workspace_context.py`).
- Features podem ser gated por módulo (`module_gate` / `ModuleRoute` no frontend).

### Entrada da API

Arquivo: `backend/app/main.py`

Rotas de domínio relevantes montadas sob `/api/...`: accounts, transactions (+ import), categories, category-groups, rules, import-logs, reports, dashboard, connections, budgets, goals, payees, invoices, workspaces, fiscal, etc.

---

## 2. Estrutura do backend FastAPI

```
backend/
├── alembic/versions/          # migrations 001–089
├── app/
│   ├── main.py                # FastAPI app + routers
│   ├── cli.py / worker.py
│   ├── api/                   # handlers HTTP (~38 módulos)
│   ├── core/                  # DB, auth, config, workspace, redis
│   ├── models/                # SQLAlchemy ORM
│   ├── schemas/               # Pydantic DTOs
│   ├── services/              # lógica de negócio (~50+ módulos)
│   ├── providers/             # bancos / open finance / FX
│   ├── tasks/                 # Celery
│   ├── fiscal/                # jurisdições TOML + validators
│   └── agents/                # opcional (AGENTS_ENABLED)
├── tests/
└── pyproject.toml
```

### Serviços centrais de finanças pessoais

| Serviço | Papel |
|---------|--------|
| `import_service` | Parse OFX/CSV/QIF/CAMT + persistência + dedup |
| `rule_engine` / `rule_service` | Avaliação e aplicação de regras; packs por país (ex.: BR) |
| `transaction_service` | CRUD, transferências, bulk categorize, listagens/P&L |
| `transfer_detection_service` | Emparelhamento automático pós-sync |
| `account_service` / `balance_service` | Contas e saldos |
| `category_service` / `category_group_service` | Taxonomia |
| `report_service` / `dashboard_service` | Relatórios e home |
| `_query_filters.counts_as_pnl` | Filtro SQL compartilhado receita/despesa |
| `connection_service` | Sync Open Finance (caminho paralelo ao import de arquivo) |
| `credit_card_service` | `effective_date` / faturas (convenções BR já presentes) |
| `recurring_match_service` | Match de recorrentes no import |
| `reconciliation_service` | Conciliação fatura↔pagamento (domínio à parte) |

---

## 3. Estrutura do frontend React/TypeScript

```
frontend/src/
├── App.tsx / main.tsx
├── pages/                 # rotas lazy-loaded
├── components/            # UI de domínio + ui/ (shadcn)
├── contexts/              # auth, workspace, collection filter
├── hooks/                 # locale, privacy, mobile (não hooks de domínio)
├── lib/api.ts             # cliente Axios monolítico + namespaces
├── lib/                   # utils (rules, categories, accounts, format…)
├── types/index.ts         # tipos de domínio
└── locales/               # i18n (inclui pt-BR)
```

### Estado e API

- **Server state:** TanStack Query (`staleTime` ~5 min).
- **Auth / workspace:** contexts + `localStorage`; header `X-Workspace-Id`.
- **Sem Redux/Zustand** para domínio financeiro.
- Proxy Vite: `/api` → backend.

### Rotas financeiras principais

| Rota | Página | Módulo |
|------|--------|--------|
| `/` | `dashboard.tsx` | sempre |
| `/transactions` | `transactions.tsx` | `transactions` |
| `/accounts`, `/accounts/:id` | `accounts.tsx`, `account-detail.tsx` | `accounts` |
| `/import` | `import.tsx` | `import` |
| `/categories` | `categories.tsx` | `categories` |
| `/rules` | `rules.tsx` | `rules` |
| `/reports` | `reports.tsx` | `reports` |

---

## 4. Modelos SQLAlchemy envolvidos

Local: `backend/app/models/`

### Núcleo financeiro

| Modelo | Tabela | Responsabilidade |
|--------|--------|------------------|
| `Account` | `accounts` | Conta (checking/savings/credit_card), saldo, moeda, CC metadata |
| `Transaction` | `transactions` | Movimento: amount absoluto + `type` credit/debit, categoria, transfer pair, import, P&L flags |
| `Category` | `categories` | Categoria; flags `treat_as_transfer`, `is_ignored`, `is_system` |
| `CategoryGroup` | `category_groups` | Agrupamento visual |
| `Rule` | `rules` | Condições/ações JSON, prioridade, ativo |
| `ImportLog` | `import_logs` | Histórico de import (transactions ou asset_orders) |
| `Payee` (+ mapping/tax ids) | `payees`, … | Beneficiários / CPF-CNPJ |
| `BankConnection` / `Institution` | … | Open Finance |
| `CreditCardBill` | `credit_card_bills` | Ciclos de fatura |
| `RecurringTransaction` | `recurring_transactions` | Recorrências |
| `TransactionSplit` / `Group*` | … | Rateios / grupos |
| `Workspace` (+ members, tax ids) | … | Tenancy + fiscal |

### Semântica de dinheiro em `Transaction`

- `amount` armazenado em valor absoluto; sentido via `type` (`credit` = entrada, `debit` = saída).
- `transfer_pair_id` liga as duas pernas de uma transferência (não é FK formal).
- `amount_primary` / `fx_rate_used` para reporting na moeda principal.
- `effective_date` vs `date` (cartão / competência).
- Exclusões de P&L: `is_ignored`, `exclude_from_pnl`, categoria `treat_as_transfer` / `is_ignored`.
- `source`: sync, ofx, csv, manual, transfer, etc.
- `import_id` → `import_logs`.

---

## 5. Migrations Alembic e estrutura PostgreSQL

Local: `backend/alembic/versions/` (revisões **001–089**).

### Evolução relevante (resumo)

| Faixa | Tema |
|-------|------|
| 001–007 | Schema inicial, rules, import_logs |
| 009–011 | category_groups, transfer_pair_id, payee/raw_data/status |
| 016–017 | FX / amount_primary |
| 025–030, 040–043 | Cartão de crédito BR (effective_date, bills) |
| 033 | `treat_as_transfer` + seed |
| 052–054 | Workspaces |
| 067 | `transfer_amount_explicit` |
| 071 | `original_description` / rule-managed description |
| 073 | Import de asset orders |
| 084–085 | Índices dashboard; `exclude_from_pnl` |
| 086–089 | Reconciliation |

### Grafo PostgreSQL (simplificado)

```
users ── workspaces ── workspace_members
              │
              ├── accounts ── transactions ── categories ── category_groups
              │                  │              payees
              │                  │              import_logs
              │                  │              credit_card_bills
              │                  │              recurring_transactions
              │                  └── transfer_pair_id (auto-relação lógica)
              ├── bank_connections ── institutions
              └── rules
```

Tipos comuns: UUID PKs, `Numeric(15,2)`, JSON para regras, timestamps com timezone.

---

## 6. APIs envolvidas

### Contas — `/api/accounts`

CRUD, summary, balance-history, bills (CC), close/reopen.

### Transações — `/api/transactions`

Listagem, calendar, export, CRUD, installments, bulk categorize/tags/group/delete, ignore, transfer create/link/counterpart/candidates/pair.

### Importação — `/api/transactions/import*` + `/api/import-logs`

| Método | Path | Função |
|--------|------|--------|
| POST | `/api/transactions/import/preview` | Preview + sugestões de categoria |
| POST | `/api/transactions/import` | Commit |
| GET/DELETE | `/api/import-logs` | Histórico / undo |

### Categorias — `/api/categories`, `/api/category-groups`

CRUD + `rule-usage` ao ocultar categoria.

### Regras — `/api/rules`

CRUD, preview, apply-all, export/import JSON, packs por país (`/rules/packs`, `/rules/packs/{code}/install`).

### Relatórios — `/api/reports`

- `GET /net-worth`
- `GET /income-expenses`
- `GET /cash-flow`

### Transferências auto (pós-sync)

- `POST /api/connections/transfers/detect`
- `DELETE /api/connections/transfers/{pair_id}`

### Dashboard — `/api/dashboard/*`

Summary, spending-by-category, monthly-trend, projected-transactions, balance-history.

---

## 7. Código de importação (OFX / CSV / QIF / CAMT)

**Módulo principal:** `backend/app/services/import_service.py`  
**API:** `backend/app/api/import_transactions.py`

| Formato | Função | Notas |
|---------|--------|-------|
| OFX/QFX | `parse_ofx` | `ofxparse`; pré-processamento BR (FITID vazio, linhas de saldo BB); encoding UTF-8/Latin-1 |
| QIF | `parse_qif` | Parser próprio (`^`-blocks), múltiplos formatos de data |
| CAMT.052/053 | `parse_camt` | ISO 20022 XML; BOOK; CRDT/DBIT |
| CSV | `parse_csv` + `detect_csv_columns` | Dialect sniff, mapeamento de colunas, inflow/outflow, FX |

**Dispatch:** por extensão do arquivo; fallback OFX → QIF → CAMT → CSV.

**Persistência:** `import_transactions(...)` — dedup, regras, recorrentes, conciliação, stamp FX, effective_date CC.

**Paralelo (não extrato bancário):** `asset_import_service.py` (ordens de investimento).

**Particularidades BR já no OFX:**

- Filtra descrições de saldo (`saldo anterior`, `saldo do dia`, …).
- Sintetiza FITID vazio (Banco do Brasil e similares).

---

## 8. Fluxo de importação

```
Upload (frontend /import)
    │
    ▼
POST /transactions/import/preview
    │  parse_* (OFX|CSV|QIF|CAMT)
    │  enrich_with_category_suggestions (regras dry-run)
    ▼
ImportReviewTable (excluir linhas / override categoria)
    │
    ▼
POST /transactions/import
    │  ImportLog
    │  dedup
    │  category: override → suggested → CSV name
    │  apply_rules_to_transaction (desc/payee/notes/ignore; cat se livre)
    │  payee get_or_create, FX stamp, CC effective_date
    │  recurring_match, reconciliation match
    ▼
Transactions + invalidate queries + import-logs
```

**Observação:** detecção automática de transferências entre contas **não** roda no caminho de import de arquivo — apenas pós-sync (`transfer_detection_service`) ou ações manuais do usuário.

---

## 9. Fluxo de categorização e regras

### Camadas

1. **Manual / bulk** — `PATCH` transaction ou `/bulk-categorize`.
2. **Sugestão no preview de import** — `enrich_with_category_suggestions`.
3. **Motor de regras** — `rule_engine` + `rule_service.apply_rules_to_transaction`.
4. **Retroativo** — `POST /api/rules/apply-all`.
5. **Pack BR** — `RULE_PACKS["BR"]` em `rule_service.py` (Pix, iFood, IPTU/IPVA, salário, etc.), instalável via API; `BRL` → país default `BR`.

### Motor (`rule_engine.py`)

- Condições AND/OR aninhadas; campos como description/amount/type/account.
- Normalização de acentos/case.
- Ações: `set_category`, `set_description`, `set_payee`, `append_notes`, `ignore`.
- Primeira regra que define categoria “vence” (ordenação por `priority`).

### Sync bancário

`connection_service` também aplica regras após sincronizar — mesmo motor do import/manual create.

---

## 10. Detecção de duplicadas

Em `import_service.import_transactions`:

1. **Com `external_id` (ex.: FITID OFX):** mesmo `account_id` + `external_id` + `date` (data incluída por reuso de FITID em parcelas BR).
2. **Sem external_id:** `account_id` + `date` + `amount` + `type` + (`description` OU `original_description`).
3. CSV pode desligar dedup (`detect_duplicates=False`); OFX/QIF/CAMT sempre detectam.

---

## 11. Receitas, despesas e transferências

### P&L — `counts_as_pnl()` (`_query_filters.py`)

Exclui do total de receita/despesa:

- pares com `transfer_pair_id`;
- `is_ignored` / `exclude_from_pnl`;
- categorias `treat_as_transfer` ou `is_ignored`;
- débitos de settlement (evita double-count).

**Receita** = soma de `credit` (tipicamente `amount_primary`).  
**Despesa** = soma absoluta de `debit`.

Usado por listagem (summary), `report_service`, `dashboard_service`.

### Transferências entre contas

| Mecanismo | Onde |
|-----------|------|
| Criação explícita | `POST /transactions/transfer` → duas txs + `transfer_pair_id`, `source=transfer` |
| Link manual | link-transfer / create-counterpart / candidates |
| Auto-detect | `transfer_detection_service`: debit↔credit, contas distintas, mesmo valor abs, janela ±2 dias; pós-sync |
| Categoria “como transferência” | `treat_as_transfer` (ex.: aplicação em investimento sem conta contraparte) — sai do P&L sem pair |

---

## 12. Componentes frontend envolvidos

### Transações

- `pages/transactions.tsx`
- `transaction-dialog.tsx`, `transaction-calendar-view.tsx`, `transaction-drill-down.tsx`
- `transactions-filter-bar.tsx`, `transactions-page-actions.tsx`, grid/mobile helpers
- `transfer-dialog.tsx`, `link-transfer-dialog.tsx`
- `category-select.tsx`, `rule-dialog.tsx` (criar regra a partir da seleção)

### Categorias

- `pages/categories.tsx`
- `category-icon.tsx`, `category-select.tsx`, `category-filter-*`, `icon-picker.tsx`

### Importação

- `pages/import.tsx` (abas transactions + investments)
- `import-review-table.tsx`, `import-summary-bar.tsx`, `import-history.tsx`
- `asset-import-panel.tsx` (investimentos)

### Contas

- `pages/accounts.tsx`, `pages/account-detail.tsx`
- `account-icon.tsx`, `account-*-actions.tsx`
- diálogos de conexão: Pluggy / OAuth / token / settings

### Dashboard

- `pages/dashboard.tsx` (+ drill-down, month-stepper, badges de projetadas)

### Relatórios

- `pages/reports.tsx`
- `components/reports/CashflowSankey.tsx` (Money Map)

### Regras

- `pages/rules.tsx`, `rule-dialog.tsx`
- abas de reconciliation (domínio fatura, não categorização de gasto)

### Cliente API

Namespaces em `frontend/src/lib/api.ts`: `transactions`, `accounts`, `categories`, `rules`, `importLogs`, `dashboard`, `reports`, `connections`, …

---

## 13. Testes relacionados

### Importação

| Arquivo | Cobertura |
|---------|-----------|
| `tests/test_import_service.py` | Parse CSV/QIF/CAMT/OFX, FX, categoria, dedup, regras |
| `tests/test_import_api.py` | Preview/import/logs/duplicates/sugestões |
| `tests/test_import_warnings.py` | Warnings |
| `tests/test_recurring_match_import.py` | Match de recorrentes no import |
| `tests/test_asset_import_*.py` | Import de ativos (paralelo) |

### Transações / transferências

| Arquivo | Foco |
|---------|------|
| `test_transaction_service.py` (+ coverage) | CRUD, regras no create, transfers, FX, ignore |
| `test_transactions_api.py` (+ coverage) | HTTP, P&L, export, bulk categorize |
| `test_transfer_api.py`, `test_transfer_detection.py` | Transferências e auto-pair |
| `test_transaction_installments.py`, `test_transaction_calendar_service.py`, `test_transaction_splits_api.py` | Parcelas, calendário, splits |

### Categorização / regras

| Arquivo | Foco |
|---------|------|
| `test_rule_engine.py`, `test_rule_service.py`, `test_new_rules_api.py` | Motor + API |
| `test_category_service.py`, `test_categories_api.py` | Categorias |
| `test_category_group_*` | Grupos |

### Relatórios

- `test_report_service.py`, `test_report_service_coverage.py`

---

## 14. Pontos de extensão naturais

| Ponto | Por que estender aqui |
|-------|------------------------|
| `import_service.parse_*` | Novos formatos BR (CNAB, OFX de bancos específicos, CSV de apps) |
| Dedup em `import_transactions` | Heurísticas Pix (mesmo valor, datas próximas, descrições “PIX …”) |
| `RULE_PACKS["BR"]` | Expandir merchants, bancos, boletos, débito automático |
| `rule_engine` | Novos campos/ações (ex.: marcar transferência, tags BR) |
| `transfer_detection_service` | Rodar também pós-import; janelas/heurísticas Pix |
| `counts_as_pnl` / reports | Relatórios BR (fluxo de caixa competência vs caixa; cartão) |
| `credit_card_service` | Ciclos de fatura / parcelamento brasileiro |
| `fiscal/jurisdictions/br.toml` + payees | CPF/CNPJ em contrapartes |
| Pluggy (`providers`) | Cobertura Open Finance Brasil |
| Categorias default / setup | Taxonomia pt-BR alinhada a PF brasileira |
| Módulos frontend (`ModuleRoute`) | Ligar/desligar superfícies no produto BR |
| i18n `pt-BR` | Copy e formatos BRL (já parcialmente presentes) |

---

## Plano de adaptação para Gestão Financeira Brasil

Objetivo: posicionar o Securo como **gestão financeira pessoal para o mercado brasileiro**, reaproveitando a base já orientada a workspace, import, regras, cartão e Open Finance — sem reescrever o core.

### Fase 0 — Baseline (sem código funcional novo)

- Usar este documento como mapa de hotspots.
- Inventariar gaps BR vs produto atual (Pix, boleto, cartão, Open Finance, IRPF auxiliar).
- Definir MVP: contas + import OFX/CSV + regras BR + dashboard P&L + transferências.

### Fase 1 — Experiência e taxonomia BR

- Garantir onboarding com idioma `pt-BR`, moeda `BRL`, pack de regras `BR` instalável/automático no setup.
- Revisar categorias/grupos default em português alinhados a PF (moradia, transporte, saúde, impostos IPTU/IPVA, salário, Pix).
- Expandir `RULE_PACKS["BR"]` com padrões reais de extrato (Nubank, Inter, Itaú, BB, Caixa, Bradesco).
- UX de import: presets de CSV dos bancos/apps brasileiros mais comuns.

### Fase 2 — Import e qualidade de dados

- Endurecer OFX BR (já há patches BB); cobrir quirks de outros bancos com testes em `test_import_service.py`.
- Melhorar dedup para Pix e parcelas (FITID reutilizado).
- Opcional: disparar `transfer_detection` após import de arquivo (hoje só pós-sync).
- Tratar descrições “PIX ENVIADO/RECEBIDO” como candidatas a transferência ou `treat_as_transfer` conforme regra de negócio.

### Fase 3 — Cartão, boletos e recorrência

- Aproveitar `credit_card_bills` / `effective_date` / parcelas já modelados.
- Fluxos claros de fatura vs compra (P&L vs saldo).
- Recorrentes tipicamente BR: aluguel, condomínio, streaming, energia, telecom.
- (Opcional MVP+) lembretes/boletos como metadado em payee ou notas — sem NF-e completa no MVP PF.

### Fase 4 — Open Finance e instituições

- Pluggy como caminho preferencial BR (`providers`).
- Instituições, logos, reconexão, sync assets (Tesouro já aquecido no lifespan).
- Documentar limitações sandbox vs produção.

### Fase 5 — Relatórios e educação financeira BR

- Relatórios existentes (net worth, income-expenses, cash-flow, Money Map) com copy e defaults BRL.
- Visões úteis PF: gastos por categoria no mês, tendência, cartão vs débito, “quanto sobrou”.
- Evitar prometer IRPF completo no MVP; eventual export auxiliar depois.

### Fase 6 — Fiscal leve (não contábil)

- CPF/CNPJ já no fiscal registry BR e payees — usar em contrapartes.
- Não misturar NFS-e/fatura empresarial com PF até haver produto B2B separado (o código de invoices é rico e BR-aware, mas é outro produto).

### Princípios de adaptação

1. **Estender serviços existentes** (`import_service`, `rule_service`, `transfer_detection_service`) em vez de forks paralelos.
2. **Testes primeiro** nos módulos listados na seção 13 ao mudar dedup/parse/regras.
3. **Workspace + módulos** para fatiar o produto BR sem remover capabilities internacionais.
4. **Pix e cartão** como eixos de diferenciação; OFX/CSV como onboarding offline.
5. **Nenhuma alteração funcional** até o plano de implementação por epic ser aprovado.

### Ordem sugerida de epics técnicos

1. Setup BR default (locale, BRL, rule pack, categorias).  
2. Import BR (presets CSV + quirks OFX + dedup Pix).  
3. Transferências pós-import + UX Pix.  
4. Cartão/fatura polish.  
5. Dashboard/relatórios copy + KPIs PF.  
6. Open Finance Pluggy hardening.  
7. Fiscal leve (CPF/CNPJ em payees) se necessário ao MVP.

---

## Referências rápidas de arquivos

| Tema | Caminho |
|------|---------|
| App FastAPI | `backend/app/main.py` |
| Import | `backend/app/services/import_service.py`, `backend/app/api/import_transactions.py` |
| Regras / pack BR | `backend/app/services/rule_service.py`, `rule_engine.py` |
| P&L | `backend/app/services/_query_filters.py` |
| Transfer auto | `backend/app/services/transfer_detection_service.py` |
| Models | `backend/app/models/transaction.py`, `account.py`, `category.py`, `rule.py`, `import_log.py` |
| Frontend API | `frontend/src/lib/api.ts` |
| Páginas core | `frontend/src/pages/{dashboard,transactions,accounts,import,categories,rules,reports}.tsx` |
| Fiscal BR | `backend/app/fiscal/jurisdictions/br.toml` |
