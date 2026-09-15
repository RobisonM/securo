# Plano de Normalização de Transações — Securo (Brasil)

Documento de análise do modelo financeiro existente e do plano de adaptação semântica para gestão financeira pessoal no mercado brasileiro.

**Escopo:** somente análise. Nenhuma alteração funcional, migration, model, API ou frontend foi feita nesta etapa.

**Referências:** `docs/ARCHITECTURE_ANALYSIS.md`, `.cursor/rules/personal-finance.mdc`

**Data:** 2026-09-14

---

## 1. Resumo executivo

O modelo `Transaction` do Securo **já cobre a maior parte dos requisitos financeiros** com campos existentes e filtros de P&L. A semântica correta de receita/despesa/transferência/ajuste **não exige um novo enum `type`** no banco.

| Requisito | Status |
|-----------|--------|
| 1. Receitas | **JÁ SUPORTADO** (`type=credit` + `counts_as_pnl`) |
| 2. Despesas | **JÁ SUPORTADO** (`type=debit` + `counts_as_pnl`) |
| 3. Transferências entre contas próprias | **JÁ SUPORTADO** (`transfer_pair_id`); gap: auto-detecção não roda após import de arquivo |
| 4. Compras no cartão | **JÁ SUPORTADO** (débitos em `account.type=credit_card` contam como despesa) |
| 5. Pagamento de fatura | **JÁ SUPORTADO** quando as duas pernas são emparelhadas; gap se só o banco for importado e não houver pair/`treat_as_transfer` |
| 6. Estornos | **Parcial** (créditos/débitos invertidos); sem tipo dedicado |
| 7. Ajustes | **JÁ SUPORTADO** (`exclude_from_pnl`) |
| 8. Não classificadas | **JÁ SUPORTADO** (`category_id IS NULL` + `pending_categorization` no dashboard) |
| 9. Importação repetida sem duplicação | **JÁ SUPORTADO** para OFX com FITID; gaps em FITID ausente / CSV / falsos positivos BR |
| 10. Conciliação extrato bancário ↔ cartão | **Não é o papel de `reconciliation_service`** (esse é fatura/invoice ↔ dinheiro). Emparelhamento banco↔cartão = `transfer_detection_service` |

**Princípio confirmado pelo código:** não criar novos campos enquanto a semântica puder ser derivada de `type` + `source` + `transfer_pair_id` + flags de categoria/P&L + metadados de import.

Os rótulos desejados (`income`, `expense`, `transfer`, `card_payment`, `adjustment`, `uncertain`) devem ser tratados como **classificação derivada (view/DTO)**, não como substituição do `type` debit/credit.

---

## 2. Modelo atual

### 2.1 Entidades centrais

| Entidade | Arquivo | Papel |
|----------|---------|-------|
| `Transaction` | `backend/app/models/transaction.py` | Movimento monetário |
| `Account` | `backend/app/models/account.py` | Conta (`checking` / `savings` / `credit_card`) |
| `Category` | `backend/app/models/category.py` | Taxonomia + `treat_as_transfer` / `is_ignored` |
| `ImportLog` | `backend/app/models/import_log.py` | Lote de importação |
| `CreditCardBill` | `backend/app/models/credit_card_bill.py` | Fatura / ciclo do cartão |

### 2.2 Mapeamento campo a campo

| Campo | Representa hoje | Adequado? | Gap |
|-------|-----------------|-----------|-----|
| `source` | Origem: `sync`, `ofx`, `csv`, `manual`, `transfer`, `settlement`, `opening_balance`, … | Sim | Sem enum rígido; valores livres em string |
| `account_id` | Conta dona do movimento | Sim | — |
| `external_id` | ID do provedor / FITID OFX | Sim | Vazio em muitos OFX BR → cai no fallback |
| `date` | Data do lançamento no extrato | Sim | — |
| `effective_date` | Data de caixa/fluxo (CC → vencimento da fatura) | Sim | Import sem `bill_id` usa só cycle math |
| `original_description` | Texto bruto preservado | Sim | — |
| `description` | Texto exibido (pode ser alterado por regra) | Sim | Não há coluna “descrição normalizada” separada; normalização é só em memória (ex.: filtro OFX de saldo) |
| `payee` / `payee_id` | Beneficiário texto + entidade | Sim | Sem categorização por histórico de payee |
| `amount` | Valor absoluto `Numeric(15,2)` / `Decimal` | Sim | — |
| `amount_primary` | Valor na moeda principal do workspace | Sim | — |
| `type` | **Somente** `debit` \| `credit` | Sim para ledger | Não expressa `income`/`transfer`/`card_payment` como tipo; isso é **derivado** |
| `category_id` | Categoria (nullable = não categorizada) | Sim | — |
| `transfer_pair_id` | Emparelhamento bilateral conta↔conta | Sim | Não preenchido automaticamente no import de arquivo |
| `is_ignored` | Some do saldo e do P&L | Sim | — |
| `exclude_from_pnl` | Ajuste de saldo: fica no ledger, sai do P&L | Sim | Pouco surfado no fluxo de import |
| `import_id` | FK → `import_logs` | Sim | Segunda importação cria novo `ImportLog` mesmo com 0 txs |
| `raw_data` | Payload bruto JSON | Sim | — |
| `bill_id` | FK → fatura do cartão | Sim | Principalmente no sync Pluggy |
| `status` | `posted` / `pending` | Sim | — |

### 2.3 Filtro de P&L

**JÁ SUPORTADO PELO SECURO** — `backend/app/services/_query_filters.py` → `counts_as_pnl()`:

Exclui:

- `transfer_pair_id IS NOT NULL`
- `is_ignored`
- `exclude_from_pnl`
- categorias com `treat_as_transfer` ou `is_ignored`
- débitos com `source=settlement`

Receita = créditos que passam no filtro. Despesa = débitos que passam no filtro.

---

## 3. O que já atende nossos requisitos

### 3.1 Receitas e despesas

**JÁ SUPORTADO PELO SECURO**

- Arquivos: `transaction.py` (`type`), `_query_filters.py` (`counts_as_pnl`), `report_service.py`, `dashboard_service.py`
- Valores monetários já usam `Decimal` / `Numeric` (alinhado à rule de personal finance)

### 3.2 Transferências manuais e pós-sync

**JÁ SUPORTADO PELO SECURO**

- Criação: `transaction_service.create_transfer` — duas pernas, `source=transfer`, mesmo `transfer_pair_id`
- Auto pós-sync: `transfer_detection_service.detect_transfer_pairs` chamado por `connection_service`
- API manual: `POST /api/connections/transfers/detect`
- Link manual: `POST /api/transactions/link-transfer`, `create-counterpart`
- P&L: ambas as pernas saem via `transfer_pair_id`

### 3.3 Categoria “como transferência” (unilateral)

**JÁ SUPORTADO PELO SECURO**

- `Category.treat_as_transfer` (ex.: Transfers, Investments)
- Pack BR categoriza Pix Enviado/Recebido → categoria `transfers` (`rule_service.RULE_PACKS["BR"]`)
- Sai do P&L **sem** exigir pair (útil para investimento / Pix sem contraparte importada)

### 3.4 Compras no cartão

**JÁ SUPORTADO PELO SECURO**

- Conta `type=credit_card`
- Débitos de compra entram no P&L como despesa
- `effective_date` / `CreditCardBill` / `credit_card_service.apply_effective_date` para competência de fluxo de caixa
- Parcelas: campos `installment_*`

### 3.5 Ajustes de saldo

**JÁ SUPORTADO PELO SECURO**

- `exclude_from_pnl=True` — permanece no saldo, fora de receita/despesa
- Model comment em `transaction.py` descreve exatamente esse caso

### 3.6 Pendente de categorização

**JÁ SUPORTADO PELO SECURO**

- `category_id IS NULL`
- Dashboard: `pending_categorization` / `pending_categorization_amount` (`dashboard_service.py`)
- Listagem: filtro `uncategorized=true` (exclui pares de transferência)
- Relatórios: bucket `"uncategorized"`

### 3.7 Deduplicação de import OFX com FITID

**JÁ SUPORTADO PELO SECURO**

- `import_service.import_transactions`: match `account_id + external_id + date`
- Reimport idêntico → `imported=0`, `skipped=N`
- Testes: `tests/test_import_service.py`
- Quirks BR: linhas de saldo OFX filtradas; FITID vazio sintetizado só para parse e depois descartado

### 3.8 Auditoria básica de import

**JÁ SUPORTADO PELO SECURO** (quase completo)

- `source`, `account_id`, `external_id`, `import_id`, `original_description`, `description`, `date`, `amount`, `raw_data`
- Gap leve: não há coluna explícita de “descrição normalizada”

---

## 4. Gaps reais encontrados

### G1 — Detecção de transferência não roda após import de arquivo (P0/P1)

- `import_service` termina com `reconciliation_service.match_incoming` (invoices), **não** com `detect_transfer_pairs`
- Cenário A (Itaú Pix −1000 / Nubank Pix +1000) após dois OFX: pode gerar **despesa + receita** até o usuário detectar/linkar manualmente
- Cenário B (pagamento fatura): banco −805 + crédito no cartão +805 podem **não** emparelhar automaticamente no caminho só-arquivo

### G2 — Pack BR trata Pix genérico como `transfers` (P1)

- Regras `PIX.*ENVIADO|PIX.*TRANSF` e `PIX.*RECEBIDO` → categoria Transfers (`treat_as_transfer`)
- Isso **remove do P&L** mesmo quando o Pix é pagamento a terceiro (despesa real) ou recebimento de cliente (receita real)
- Conflita com o princípio: “não considerar automaticamente todo PIX como transferência”

### G3 — Pagamento de fatura sem pair / sem categoria transfer (P0)

- Se só existir o débito “PAGAMENTO CARTAO” na conta corrente e ele **não** for categorizado como transfer nem emparelhado:
  - Compras no cartão = R$ 805 (despesa) ✅
  - Pagamento = R$ 805 (despesa) ❌ → total R$ 1.610
- Com pair (`transfer_pair_id`) ou categoria `treat_as_transfer`: pagamento sai do P&L ✅

### G4 — Sem classificação derivada explícita (P2)

- Product rules pedem `income | expense | transfer | card_payment | adjustment | uncertain`
- Hoje isso está **implícito** e espalhado; não há DTO/helpers únicos
- Risco: inconsistência entre dashboard, reports e UI

### G5 — Estornos / uncertain sem semântica dedicada (P2)

- Estorno = tipicamente `credit` no cartão ou `debit` invertido
- Sem flag/confiança; pode virar “receita” no P&L se não for tratado
- “Uncertain” ≈ não categorizada + (futuro) score baixo — score **não existe** hoje

### G6 — Dedup: falsos positivos/negativos BR (P1)

| Situação | Risco |
|----------|-------|
| FITID reutilizado em parcelas, **datas diferentes** | Correto: ambas importam (já tratado) |
| FITID ausente + mesma descrição/valor/data | Dedup por campos OK |
| Dois Pix distintos mesmo valor/data/descrição genérica | Falso positivo no fallback |
| Descrição muda entre extratos do mesmo banco | Falso negativo no fallback |
| CSV com `detect_duplicates=False` | Duplicatas intencionais possíveis |
| Reimport cria novo `ImportLog` com count 0 | Ruído de auditoria (baixo) |

### G7 — `reconciliation_service` ≠ conciliação cartão (documentação/produto) (P2)

- Nome sugere “reconciliação bancária ampla”, mas o serviço reconcilia **invoices/recorrentes ↔ dinheiro**
- Conciliação fatura cartão ↔ pagamento = transfer pairing + bills

### G8 — Categorização: ordem incompleta vs roadmap desejado (P1/P2)

Ordem atual efetiva:

1. Override manual no review de import / `force_uncategorized`
2. `suggested_category_id` (preview = regras dry-run)
3. Nome de categoria no CSV
4. `apply_rules_to_transaction` (não sobrescreve categoria já setada)
5. Pack BR = regras instaláveis (não merchant DB / alias / histórico / IA)

**Ausentes:** merchant conhecido, alias, histórico de classificação, confiança, IA.

### G9 — Auto-pair sem checagem de descrição (P1 se ativar pós-import)

- Algoritmo atual: valor abs + contas distintas + ±2 dias; **sem** texto
- Indexação por `float(amount)` — risco teórico de precisão
- Falsos positivos: dois lançamentos coincidentes de mesmo valor

---

## 5. Alterações que NÃO são necessárias

| Ideia tentadora | Por que NÃO |
|-----------------|-------------|
| Novo enum DB `type = income/expense/transfer/...` | Quebra ledger debit/credit; semântica já derivável |
| Coluna `is_transfer` | Redundante com `transfer_pair_id` + `treat_as_transfer` |
| Coluna `is_card_payment` | Derivável: debit em checking/savings + credit/pair em `credit_card` (ou descrição + pair) |
| Coluna `is_adjustment` | Redundante com `exclude_from_pnl` |
| Coluna `pending_categorization` | Redundante com `category_id IS NULL` |
| Novo serviço de “reconciliação CC” separado | Reusar `transfer_detection` + `CreditCardBill` |
| Substituir `ImportLog` | Já atende lote/auditoria |
| Float para dinheiro | Já proibido / já evitado no model (`Numeric`/`Decimal`) |
| Migration só para “descrição normalizada” no MVP | Pode ser função pura na camada de serviço até provar necessidade de persistência |

---

## 6. Alterações recomendadas

Ordem conceitual (detalhe nas seções 11–18):

1. **Documentar e implementar classificação derivada** (helper puro) sem migration.
2. **Corrigir/afrouxar regras Pix do pack BR** (comportamento, não schema).
3. **Chamar detecção de transferências após import** com guards (account types, opcional heurística de texto).
4. **Heurística/sugestão de pagamento de fatura** quando houver crédito em CC no período.
5. **Melhorar dedup** (opcional: fingerprint estável; alertas de skip).
6. **Pipeline de categorização com confiança** (posterior; P2/P3).
7. **UI** para revisar uncertain / sugerir pairs (posterior).

---

## 7. Alterações de banco / migrations

**Conclusão: nenhuma migration é necessária para o MVP de normalização semântica.**

| Possível migration futura | Quando justificar |
|---------------------------|-------------------|
| `description_normalized` persistida | Se busca/dedup/regras exigirem índice em escala |
| Índice único parcial `(account_id, external_id, date)` WHERE external_id IS NOT NULL | Endurecer idempotência no DB (hoje é lógica de serviço) |
| `categorization_confidence` / `categorization_source` | Pipeline com IA/histórico |
| Enum check constraint em `transactions.type` | Higiene (`debit`/`credit` only) — opcional |

**Não criar** colunas para os rótulos income/expense/transfer/card_payment/adjustment/uncertain.

---

## 8. Alterações em services

| Serviço | Mudança recomendada |
|---------|---------------------|
| Novo helper (ex. `transaction_classification.py`) | Função pura: classifica tx → `income \| expense \| transfer \| card_payment \| adjustment \| uncertain` com base em campos existentes |
| `import_service` | Após persistir lote, chamar detecção de transfers (ver §12/§F); retornar contagem de paired/skipped |
| `transfer_detection_service` | Opcional: filtros (evitar pair entre duas despesas coincidentes); preferir bank↔bank e bank↔credit_card; não usar float como chave |
| `rule_service` (pack BR) | Remover ou restringir Pix genérico → Transfers; separar “Pix próprio” vs “Pix pagamento” |
| `credit_card_service` / detection | Sugerir pair quando debit banco ≈ soma fatura / crédito CC |
| `_query_filters` | **Manter**; eventualmente documentar mapping classificação→filtro |
| `reconciliation_service` | **Não reaproveitar** para CC; no máximo renomear docs/comentários de produto |

---

## 9. Alterações em APIs

**Nenhuma breaking change necessária no MVP.**

Possíveis adições posteriores (não nesta etapa):

- Campo derivado `classification` em `TransactionRead`
- Resposta de import: `transfers_paired`, `duplicates_skipped`
- Query `?classification=` / `?uncertain=true` (alias de uncategorized + flags)
- Endpoint existente `POST /connections/transfers/detect` permanece; import pode reutilizá-lo internamente

---

## 10. Alterações no frontend

**Nenhuma nesta etapa.** Futuro:

- Badge/filtro por classificação derivada
- CTA pós-import: “N transferências sugeridas”
- Aviso quando débito parece pagamento de cartão sem pair
- Revisar copy do pack BR / regras Pix
- Manter fluxo “Sem categoria” existente (`pending_categorization`)

---

## 11. Estratégia de deduplicação

### Atual (manter)

```
SE external_id:
  match (account_id, external_id, date)
SENÃO:
  match (account_id, date, amount, type, description OR original_description)
```

OFX/QIF/CAMT: sempre on. CSV: toggle `detect_duplicates`.

### Recomendações

1. **Manter** chave com `date` por causa de parcelas BR (FITID reutilizado).
2. **Não** deduplicar só por FITID sem data.
3. Melhorar fallback BR (P2): normalizar descrição (remover “PIX ENVIADO”, CPF mascarado) **em memória** antes do match.
4. Opcional P2: unique index parcial no Postgres para corridas concurrentes.
5. Auditoria: mesmo com 0 importados, registrar `ImportLog` é aceitável; expor `skipped` claramente na UI.

### Falsos positivos / negativos BR

| Caso | Mitigação |
|------|-----------|
| Dois Pix R$ 50 no mesmo dia, texto idêntico | Exigir `external_id` quando disponível; UI de revisão |
| Parcela 3/12 mesmo FITID datas diferentes | Já OK |
| Reimport após regra renomear description | Já compara `original_description` |
| Extrato sem FITID | Fallback; aceitar risco residual |

---

## 12. Estratégia de transferências

### Cenário A — Itaú −1000 / Nubank +1000

**Resultado esperado:** zero receita, zero despesa.

| Mecanismo | Efeito |
|-----------|--------|
| `transfer_pair_id` preenchido | **JÁ SUPORTADO** — ambas fora do P&L |
| Só categoria Transfers (`treat_as_transfer`) | Fora do P&L, mas **sem** vínculo bilateral (aceitável temporariamente) |
| Nada | **Gap** — −1000 despesa + +1000 receita |

### Quando chamar `detect_transfer_pairs` após import

**Recomendação: SIM, chamar após `import_transactions`, com cuidados.**

| Item | Detalhe |
|------|---------|
| **Onde** | Final de `import_service.import_transactions`, após flush das novas txs, **antes** ou **depois** de `match_incoming` (preferir depois do commit parcial das txs, antes do commit final — mesmo padrão do sync) |
| **Quando** | Se `imported > 0` e workspace tem ≥ 2 contas; passar `candidate_ids=ids_das_novas_txs` (API já existe no detector) |
| **Riscos** | Falsos positivos por valor coincidente; Pix a terceiro pareado com crédito alheio |
| **Performance** | O(n) sobre unpaired; OK para lotes típicos de extrato; monitorar workspaces grandes |
| **Falsos positivos** | Mitigar: (1) priorizar pair bank↔bank ou bank↔CC; (2) opcional overlap de tokens Pix/TRANSFER; (3) não pairar se já categorizadas como despesa merchant com alta confiança (futuro) |
| **Testes** | Import dois OFX simulados; assert `transfer_pair_id` e P&L zero; caso negativo: Uber R$ 50 + depósito R$ 50 não pareiam se datas/contas/heurística forem restritas |

### Manual

Manter create/link/detect endpoints — **JÁ SUPORTADO**.

---

## 13. Estratégia para cartão / fatura

### Cenário B — Compras R$ 805 + pagamento banco R$ 805

**Resultado esperado:** despesa total = R$ 805 (não 1610).

| Peça | Papel |
|------|-------|
| Compras (debits CC) | Contam como **expense** via `counts_as_pnl` — **JÁ SUPORTADO** |
| Pagamento (debit banco + credit CC) | Deve virar **transfer / card_payment** via `transfer_pair_id` — **JÁ SUPORTADO** se detectado |
| `CreditCardBill` | Organiza fatura; **não** duplica despesa sozinho |
| `counts_on_bill` | Total da fatura ≠ P&L (compras vs pagamento) — **JÁ SUPORTADO** |
| `reconciliation_service` | **Não** resolve este caso |

### Classificação derivada sugerida

```
card_payment SE:
  (transfer_pair_id IS NOT NULL
   E uma perna em account.type=credit_card
   E a outra em checking/savings)
  OU (categoria treat_as_transfer E descrição ~ pagamento cartão E conta banco)
```

### Plano

1. P0: garantir pair automático pós-import/sync para pagamento↔crédito CC.
2. P1: se só existir perna banco, sugerir categoria Transfers / `exclude_from_pnl` **não** — preferir Transfers/`treat_as_transfer` ou pair quando crédito CC existir.
3. Não marcar compras CC como transfer.

---

## 14. Estratégia de categorização

### Ordem desejada (roadmap) vs atual

| # | Desejado | Atual |
|---|----------|-------|
| 1 | Regra específica do usuário | Sim (`rules`, priority) |
| 2 | Merchant conhecido | **Não** |
| 3 | Alias do merchant | **Não** |
| 4 | Regra por descrição | Sim (contains/starts_with) |
| 5 | Regra regex | Sim |
| 6 | Histórico de classificação | **Não** |
| 7 | Sugestão IA | **Não** (agents opcional, fora do core) |
| 8 | Revisão manual | Sim (import review + UI) |

### “Pendente de categorização” sem duplicar

**JÁ SUPORTADO PELO SECURO** — usar `category_id IS NULL`.

Não criar status paralelo. Extensão futura:

- `uncertain` = `category_id IS NULL` **ou** (futuro) `confidence < limiar` com categoria sugerida mas **não aplicada**
- Regra: **nunca aplicar automaticamente** abaixo do limiar — só preencher `suggested_*` (padrão já usado no preview de import)

### Pack BR

Revisar regras Pix (ver §15). Manter merchants (iFood, 99, etc.) como regras de descrição — são P1 úteis.

---

## 15. Casos especiais PIX

**Não tratar todo PIX como transferência.**

| Exemplo | Interpretação provável | Representação recomendada |
|---------|------------------------|---------------------------|
| `PIX ENVIADO JOAO SILVA` (terceiro) | Despesa / pagamento | `expense` + categoria (pessoas, serviços…); **não** Transfers automático |
| `PIX RECEBIDO MARIA` (terceiro) | Receita / reembolso | `income` + categoria |
| `PIX TRANSF NUBANK` (conta própria) | Transferência | `transfer_pair_id` quando houver contraparte; senão sugerir pair |
| `PIX QR CODE IFOOD` | Despesa consumo | `expense` + Food (regra merchant) |
| `PIX PAGAMENTO MERCADO` | Despesa | `expense` + groceries |

### Como distinguir

1. **Emparelhamento** (sinal mais forte): mesmo valor, contas próprias, janela de datas → `transfer_pair_id`.
2. **Lista de contas próprias / instituições do workspace**: “NUBANK”, “ITAÚ” no texto + pair candidato.
3. **Merchant rules** (iFood, Mercado Livre) antes de regras genéricas Pix.
4. **Não** instalar regra genérica `PIX.*ENVIADO → transfers` como default agressivo.
5. Na dúvida → deixar **uncategorized** (`category_id NULL`) / classificação `uncertain` derivada — revisão manual.

### Gap atual a corrigir (comportamento)

Pack BR hoje força Transfers em Pix Enviado/Recebido → remove do P&L indevidamente.  
**Alteração recomendada:** remover ou elevar especificidade (ex.: só quando houver token de banco próprio / após pair).

---

## 16. Testes necessários

| Área | Casos |
|------|-------|
| P&L transfer | Duas contas Pix ±1000 paired → income=0 expense=0 |
| P&L cartão | 4 compras 805 + pagamento paired → expense=805 |
| P&L cartão regressão | Pagamento **sem** pair → documentar falha atual; após fix, expense=805 |
| Import idempotente | Mesmo OFX 2× → skipped, sem novas rows |
| Parcelas FITID | Mesmo FITID datas diferentes → 2 rows |
| Detecção pós-import | `import_transactions` cria pair quando contraparte existe |
| Falso positivo | Dois lançamentos R$ 100 não relacionados **não** pareiam (com heurística) |
| Pix | QR iFood permanece expense; transf Nubank vira transfer quando pairável |
| Classificação derivada | Unit tests da função pura |
| `exclude_from_pnl` | Ajuste no saldo, ausente do income-expenses |
| Uncategorized | Dashboard `pending_categorization` conta NULL category |

Arquivos de teste existentes a estender: `test_import_service.py`, `test_transfer_detection.py`, `test_transfer_api.py`, `test_report_service.py`, `test_credit_card_*`, `test_rule_service.py`.

---

## 17. Riscos

| Risco | Impacto | Mitigação |
|-------|---------|-----------|
| Auto-pair pós-import agressivo | Despesas viram transfer por coincidência | Heurísticas; candidate_ids; revisão UI |
| Afrouxar Pix→Transfers | Algumas transferências voltam ao P&L até pair | Priorizar detecção de pair |
| Unique index prematuro | Quebra dados legados duplicados | Auditar antes de migrar |
| Confundir reconciliation invoices com CC | Trabalho no serviço errado | Seguir este documento |
| Introduzir enum type novo | Migration cara + regressão global | Evitar; usar classificação derivada |
| Logs com extrato | Compliance | Manter rule de segurança; não logar raw OFX |

---

## 18. Plano de implementação incremental

### Epic 0 — Alinhamento (docs only) ✅ esta etapa

- `ARCHITECTURE_ANALYSIS.md`
- `TRANSACTION_NORMALIZATION_PLAN.md`
- Rules `.cursor/rules/personal-finance.mdc`

### Epic 1 — Integridade P&L (P0)

1. Helper de classificação derivada + testes unitários.
2. Ativar `detect_transfer_pairs` após import (com `candidate_ids`).
3. Testes cenários A e B (transfer e fatura).
4. Ajustar pack BR Pix genérico (parar de forçar Transfers).

### Epic 2 — MVP Brasil (P1)

1. Heurísticas anti-falso-positivo no detector.
2. Sugestão/UX de pairs após import (API fields only no backend primeiro).
3. Merchants BR via rules (manter/expandir pack sem Pix genérico).
4. Documentar “pendente” = `category_id IS NULL`.

### Epic 3 — Melhorias (P2)

1. Normalização de descrição para dedup/regras.
2. Histórico payee→categoria.
3. Confidence + never auto-apply abaixo do limiar.
4. Índice único parcial opcional.

### Epic 4 — Futuro (P3)

1. IA/agents para sugestão.
2. Merchant DB / aliases.
3. Persistência `description_normalized` / `categorization_source`.

---

## Tabela prioritária

| Prioridade | Alteração | Arquivos afetados | Migration? | Risco | Testes |
|------------|-----------|-------------------|------------|-------|--------|
| **P0** | Chamar `detect_transfer_pairs` após import de arquivo | `import_service.py`, possivelmente `import_transactions.py` | Não | Médio (falsos positivos) | `test_import_service`, `test_transfer_detection`, P&L A/B |
| **P0** | Garantir P&L de pagamento de fatura quando pair existe (regressão + docs de comportamento) | `_query_filters.py` (só se gap), `transfer_detection_service.py` | Não | Baixo | `test_report_service`, credit card accounting |
| **P0** | Revisar regras Pix genéricas do pack BR (não forçar Transfers) | `rule_service.py` (`RULE_PACKS["BR"]`) | Não | Médio (P&L de usuários com pack instalado) | `test_rule_service`, cenários Pix |
| **P1** | Helper de classificação derivada (`income/expense/transfer/card_payment/adjustment/uncertain`) | Novo service helper; opcionalmente schemas read | Não | Baixo | Unit tests de classificação |
| **P1** | Heurísticas no detector (tipo de conta, opcional texto) | `transfer_detection_service.py` | Não | Médio | Falsos positivos/negativos |
| **P1** | Expor na resposta de import: skipped + pairs criados | `import_service.py`, schemas import, API | Não | Baixo | `test_import_api` |
| **P1** | Expandir merchants BR sem Pix genérico | `rule_service.py` | Não | Baixo | Pack install tests |
| **P2** | Normalização de descrição para dedup | `import_service.py` | Não (MVP) | Baixo | Dedup BR cases |
| **P2** | Campo `classification` em `TransactionRead` | `schemas/transaction.py`, serialização | Não | Baixo | API contract tests |
| **P2** | Histórico payee → categoria sugerida | `payee_service` / `rule_service` | Não | Médio | Categorização |
| **P2** | Unique index parcial `(account_id, external_id, date)` | Alembic novo | **Sim** | Médio (dados legados) | Migration + import race |
| **P2** | UI badges/filtros classificação + CTA pairs | Frontend pages/components | Não | Baixo | E2E/component |
| **P3** | Confidence score + never auto-apply | models/schemas/services | Possível | Médio | Pipeline |
| **P3** | Merchant DB / aliases | Novos models | Sim | Médio | Integração |
| **P3** | `description_normalized` persistido | `transaction.py` + Alembic | **Sim** | Baixo | Busca/dedup |
| **P3** | IA sugestão (agents) | `app/agents` | Não | Alto (produto) | Opt-in |

---

## Apêndice — Classificação derivada proposta (sem schema)

Pseudocódigo alinhado ao modelo atual:

```
SE exclude_from_pnl:          → adjustment
SE transfer_pair_id:
     SE uma conta é credit_card e a outra não: → card_payment
     SENÃO: → transfer
SE category.treat_as_transfer: → transfer   # unilateral; revisar Pix
SE category_id IS NULL:       → uncertain   # pendente de categorização
SE type == credit:            → income
SE type == debit:             → expense
```

Estornos: permanecem `income`/`expense` invertidos até haver regra/pair/`is_ignored`; não exigir novo tipo no MVP.

---

## Apêndice — Respostas diretas A–F

### A) Transferências entre contas próprias

**JÁ SUPORTADO** via `transfer_pair_id` + `counts_as_pnl`.  
`treat_as_transfer` é fallback unilateral.  
Gap: import de arquivo não auto-detecta.

### B) Pagamento de cartão

Compras = despesa (**JÁ SUPORTADO**).  
Pagamento não deve ser despesa (**JÁ SUPORTADO** se paired ou `treat_as_transfer`).  
`reconciliation_service` **não** é o mecanismo.  
`CreditCardBill` / `effective_date` organizam fatura e fluxo, não duplicam P&L.

### C) Importação duplicada

**JÁ SUPORTADO** para OFX com FITID+date.  
Gaps: sem FITID; CSV toggle off; ImportLog “vazio”.

### D) PIX

Distinguir por pair + merchants + revisão; **não** regra genérica → Transfers.  
Pack BR atual é gap comportamental.

### E) Categorização / pendente

Pendente = `category_id IS NULL` (**JÁ SUPORTADO**).  
Estender com confiança depois, sem nova coluna de status.

### F) Transfer detection após import

**Sim, deve ser chamado** de `import_transactions` quando houver novas txs, com `candidate_ids`, testes de falso positivo e preferência bank↔bank / bank↔CC.

---

*Fim do plano. Nenhuma alteração de código foi realizada nesta etapa.*
