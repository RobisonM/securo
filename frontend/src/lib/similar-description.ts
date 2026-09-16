/**
 * Extract a stable description fragment suitable for a `contains` rule.
 *
 * Bank memos often embed dates, NSUs, CPF/CNPJ, PIX ids and auth codes.
 * A rule on the full string would overfit a single row. We prefer a short
 * merchant-like token; when nothing is trustworthy we return null so the
 * UI can open RuleDialog for the user to decide.
 */

const NOISE_TOKENS = new Set(
  [
    'PIX',
    'TED',
    'DOC',
    'QR',
    'CODE',
    'PAGAMENTO',
    'PAGTO',
    'PGTO',
    'COMPRA',
    'DEBITO',
    'CREDITO',
    'CARTAO',
    'CARTÃO',
    'TRANSF',
    'TRANSFER',
    'TRANSFERENCIA',
    'TRANSFERÊNCIA',
    'ENVIADO',
    'RECEBIDO',
    'ENVIO',
    'RECEBIMENTO',
    'TARIFA',
    'TAXA',
    'IOF',
    'CDC',
    'CC',
    'CPF',
    'CNPJ',
    'NSU',
    'AUTH',
    'AUT',
    'REF',
    'ID',
    'PARCELA',
    'PARC',
  ].map((t) => t.normalize('NFKD').replace(/[\u0300-\u036f]/g, '').toUpperCase()),
)

function stripAccents(value: string): string {
  return value.normalize('NFKD').replace(/[\u0300-\u036f]/g, '')
}

function isMostlyDigits(token: string): boolean {
  const digits = (token.match(/\d/g) ?? []).length
  return digits > 0 && digits >= token.length * 0.5
}

function normalizeToken(raw: string): string {
  return stripAccents(raw)
    .toUpperCase()
    .replace(/^[^A-Z0-9]+|[^A-Z0-9]+$/g, '')
    .replace(/\.COM$/, '')
    .replace(/\.BR$/, '')
}

/**
 * Return a stable `contains` value, or null when the description has no
 * trustworthy merchant-like token.
 */
export function extractStableDescriptionTerm(description: string): string | null {
  const text = description?.trim() ?? ''
  if (!text) return null

  // PIX to/from a named party is almost never a safe merchant rule.
  if (/\bPIX\s+(ENVIADO|RECEBIDO)\b/i.test(stripAccents(text))) {
    return null
  }

  const parts = text.split(/[\s*_/|\\,;:+-]+/).map(normalizeToken).filter(Boolean)
  const candidates: string[] = []

  for (const token of parts) {
    if (token.length < 4) continue
    if (NOISE_TOKENS.has(token)) continue
    if (isMostlyDigits(token)) continue
    if (/^\d+$/.test(token)) continue
    candidates.push(token)
  }

  if (candidates.length === 0) return null

  return candidates.reduce((best, cur) => (cur.length > best.length ? cur : best))
}

export type SimilarRuleDraft = {
  term: string | null
  conditionValue: string
  /** True when we found a compact merchant-like token. */
  isStable: boolean
}

export function buildSimilarRuleDraft(description: string): SimilarRuleDraft {
  const term = extractStableDescriptionTerm(description)
  if (term) {
    return { term, conditionValue: term, isStable: true }
  }
  // Fallback: full description for RuleDialog prefill — not auto-applied.
  return {
    term: null,
    conditionValue: description.trim(),
    isStable: false,
  }
}

/** Collapse bank memo noise so identical merchants compare equal. */
export function normalizeImportDescription(description: string): string {
  return stripAccents(description ?? '')
    .toLowerCase()
    .replace(/\s+/g, ' ')
    .trim()
}

/**
 * Whether two import-review rows should share a category the user just picked.
 *
 * Prefer exact normalized equality (Sicredi repeats the same truncated memo).
 * Fall back to the same stable merchant token so "DROGASIL 3034" and
 * "DROGASIL 3852" travel together without matching unrelated PIX noise.
 */
export function importDescriptionsMatch(a: string, b: string): boolean {
  const na = normalizeImportDescription(a)
  const nb = normalizeImportDescription(b)
  if (!na || !nb) return false
  if (na === nb) return true

  const termA = extractStableDescriptionTerm(a)
  const termB = extractStableDescriptionTerm(b)
  return Boolean(termA && termB && termA === termB)
}

export type ImportCategoryPropagateResult<T extends { _id: string; description: string; selected_category_id?: string | null }> = {
  next: T[]
  /** Rows (excluding the source) that received the new category. */
  propagated: number
}

/**
 * Apply a category to the edited row and to siblings in the same import list
 * whose description matches. Rows the user already categorized differently
 * are left alone.
 */
export function propagateImportCategory<
  T extends { _id: string; description: string; selected_category_id?: string | null },
>(
  rows: T[],
  sourceId: string,
  categoryId: string | null,
): ImportCategoryPropagateResult<T> {
  const source = rows.find((r) => r._id === sourceId)
  if (!source) {
    return { next: rows, propagated: 0 }
  }

  let propagated = 0
  const next = rows.map((row) => {
    if (row._id === sourceId) {
      return { ...row, selected_category_id: categoryId }
    }
    if (!importDescriptionsMatch(source.description, row.description)) {
      return row
    }
    // Keep an intentional different pick; only fill untouched (or same) rows.
    if (
      row.selected_category_id !== undefined &&
      row.selected_category_id !== categoryId
    ) {
      return row
    }
    if (row.selected_category_id === categoryId) {
      return row
    }
    propagated += 1
    return { ...row, selected_category_id: categoryId }
  })

  return { next, propagated }
}
