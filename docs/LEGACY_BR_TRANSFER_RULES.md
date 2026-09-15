# Regras legadas de categorização BR (nota técnica — Epic 2B)

## Contexto

O pack `RULE_PACKS["BR"]` deixa de instalar regras genéricas que mapeavam
descrições para a categoria Transfers (`treat_as_transfer=True`):

- `Pix Enviado` (removida no Epic 1)
- `Pix Recebido` (removida no Epic 1)
- `Transferência` — `description contains TRANSFERENCIA` (removida no Epic 2B)

Workspaces que **já instalaram** o pack antes dessas remoções ainda podem
ter as rules persistidas em `rules` (instalação é por cópia de nome; o pack
atual não as remove automaticamente).

## Como localizar por workspace

```sql
SELECT workspace_id, id, name, is_active, priority, conditions, actions
FROM rules
WHERE name IN ('Pix Enviado', 'Pix Recebido', 'Transferência')
ORDER BY workspace_id, name;
```

Ou via serviço:

```python
select(Rule).where(
    Rule.workspace_id == workspace_id,
    Rule.name.in_(["Pix Enviado", "Pix Recebido", "Transferência"]),
)
```

Identificação estável: **`Rule.name`** (string fixa do template). Não há
`pack_code` / `template_id` na tabela `rules`.

## Limpeza futura (não executar neste Epic)

Recomendação: comando administrativo **opt-in** (CLI ou endpoint admin) que:

1. Lista matches por workspace (dry-run).
2. Desativa (`is_active=False`) ou apaga apenas rules cujo `name` está na
   allowlist acima **e** cujas `conditions` ainda batem com o template
   genérico (defesa contra rename do usuário).
3. Nunca reescreve categorias Transfers.
4. Não cria migration — é operação de dados.

Reinstalar o pack BR **não** remove rules antigas (skip por nome existente).
