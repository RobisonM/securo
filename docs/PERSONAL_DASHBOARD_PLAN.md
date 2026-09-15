# Plano — Dashboard financeiro pessoal (Epic 5A)

**Escopo:** métricas e backend. Sem redesenho de UI (Epic 5B).  
**Data:** 2026-09-15  
**Migrations:** nenhuma.

---

## 1. Auditoria do que já existe

| Métrica | Já existe? | Correta? | Pode reutilizar? | Gap |
|---------|------------|----------|------------------|-----|
| Income / expense do mês | Sim — `GET /api/dashboard/summary` (`monthly_*`) | Sim via `counts_as_user_pnl` | **Sim** | Sem `net` de primeira classe |
| Net / resultado | Só no frontend (savings rate) | — | Estender summary | Adicionar `monthly_net[_primary]` |
| Gastos por categoria | Sim — `/spending-by-category` | Sim; inclui "Sem categoria" | **Sim** | UI 5B ainda filtra null; % = total do breakdown |
| Evolução mensal | Sim — `/monthly-trend` | Quase | **Sim** | Sem `net`; meses vazios omitidos; FE não consome |
| Pending uncategorized | Sim no summary | Parcial | **Sim** | Alinhar com inbox (`exclude_from_pnl`, `is_ignored`); escopo mês |
| Top merchants | Não | — | Novo sibling | `GROUP BY payee_id` / fallback description |
| Top expenses | Não | — | Novo sibling | `ORDER BY amount DESC LIMIT N` + P&L filters |
| Cartões (limite/vencimento) | Contas + bills por conta | Campos parciais | Novo sibling | Sem `closing_date` na bill; usar Account |
| Comparação período anterior | Não | — | Adiar | Não neste Epic |
| Relatórios income-expenses | `/api/reports/*` | Mesma P&L | Não duplicar no dashboard | Manter reports para analytics |

---

## 2. Definições financeiras (obrigatórias)

Fonte única: `counts_as_user_pnl()` em `_query_filters.py` (+ `status=posted`, `source != opening_balance`, contas abertas).

| Conceito | Definição |
|----------|-----------|
| **income** | `SUM(primary_amount)` onde `type=credit` e counts_as_user_pnl |
| **expense** | `SUM(abs(primary_amount))` onde `type=debit` e counts_as_user_pnl |
| **net** | `income − expense` |
| **Excluídos do P&L** | `transfer_pair_id`, `is_ignored`, `exclude_from_pnl`, settlement (user), category `treat_as_transfer` / `is_ignored` |
| **Uncategorized em expense** | **Incluído** (é gasto real) |
| **Pending** | `category_id IS NULL` ∧ `transfer_pair_id IS NULL` ∧ `exclude_from_pnl=false` ∧ `is_ignored=false` ∧ não opening/settlement — no **mês** do summary |
| **Data** | `reporting_date_col(accounting_mode)` — igual ao dashboard atual |
| **% categoria** | `total_categoria / sum(totais do breakdown) * 100` (inclui Sem categoria) |

Critério cartão:

> compras 2.155 + pagamento fatura paired → **expense = 2.155**, nunca 4.310.

---

## 3. API (preferência: estender `/api/dashboard`)

| Endpoint | Ação Epic 5A |
|----------|----------------|
| `GET /summary` | + `monthly_net`, `monthly_net_primary`; pending alinhado |
| `GET /spending-by-category` | Sem mudança de contrato (já OK) |
| `GET /monthly-trend` | + `net`; zero-fill últimos N meses |
| `GET /top-expenses` | **Novo** |
| `GET /top-merchants` | **Novo** (V1 payee/description) |
| `GET /credit-cards` | **Novo** (Account + latest bill se houver) |

Período: parâmetro `month` existente (1º do mês). Trend: `months=1..12`.

---

## 4. Cartões — campos reais

| Campo | Fonte | Status |
|-------|--------|--------|
| account_id / name | Account | OK |
| balance | Account.balance | OK |
| credit_limit | Account.credit_limit | OK se preenchido |
| available_credit | `compute_available_credit` | OK se limit existe |
| payment_due_day / next_due | Account + cycle helpers | OK se configurado |
| statement_close_day | Account | OK se configurado |
| current_bill_amount / due_date | CreditCardBill (mais recente) | OK se sync/bill existe |
| closing_date na bill | — | **Gap** — não inventar |

---

## 5. Performance

- Agregações SQL (`SUM`/`GROUP BY`/`ORDER BY`/`LIMIT`).
- Sem carregar todas as txs em Python para totals.
- Índice: já existem índices de dashboard (migrações 084–085). Sem nova migration; recomendar revisão futura se `payee_id`+date ficar lento.

---

## 6. Decimal

Cálculos internos preferem `Decimal`/`Numeric`. Schemas dashboard existentes usam `float` na borda — **preservar** para não quebrar FE; novos campos seguem o mesmo padrão na serialização.

---

## 7. Fora de escopo (5A)

Frontend redesign, Merchant model, persistir merchant_key, comparação MoM avançada, IA, Open Finance, migrations.
