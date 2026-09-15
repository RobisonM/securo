import { useTranslation } from 'react-i18next'
import { Button } from '@/components/ui/button'
import type { CategorySuggestion } from '@/types'

type CategorySuggestionActionsProps = {
  suggestion: CategorySuggestion
  onAccept: (categoryId: string) => void
  disabled?: boolean
  compact?: boolean
}

function reasonKeyFor(code: CategorySuggestion['reason_code']): string {
  switch (code) {
    case 'same_payee':
      return 'transactions.suggestionReasonPayee'
    case 'same_merchant':
      return 'transactions.suggestionReasonMerchant'
    case 'same_description_signature':
    case 'similar_description':
    default:
      return 'transactions.suggestionReasonSimilar'
  }
}

/**
 * Discrete historical suggestion chip for the pending-inbox rows (Epics 3A/3B).
 * Accepting calls the existing PATCH categorize path — never auto-applies.
 */
export function CategorySuggestionActions({
  suggestion,
  onAccept,
  disabled = false,
  compact = false,
}: CategorySuggestionActionsProps) {
  const { t } = useTranslation()
  const reasonKey = reasonKeyFor(suggestion.reason_code)
  const basedOn =
    suggestion.reason_code === 'same_merchant' && suggestion.identity_label
      ? t('transactions.suggestionBasedOnMerchant', {
          merchant: suggestion.identity_label,
        })
      : suggestion.reason_code === 'same_payee'
        ? t('transactions.suggestionBasedOnPayee')
        : null

  return (
    <div
      className={compact ? 'space-y-1' : 'mt-1.5 space-y-1'}
      data-testid="category-suggestion"
      title={basedOn ?? suggestion.reason}
      onClick={(e) => e.stopPropagation()}
      onKeyDown={(e) => e.stopPropagation()}
    >
      <p className="text-[11px] text-muted-foreground leading-snug">
        <span className="font-medium text-foreground/80">
          {t('transactions.suggestionLabel')}: {suggestion.category_name}
        </span>
        <span className="mx-1 text-muted-foreground/50">·</span>
        <span>
          {t(reasonKey, {
            matched: suggestion.matched_count,
            total: suggestion.total_count,
            category: suggestion.category_name,
            merchant: suggestion.identity_label ?? '',
          })}
        </span>
      </p>
      <div className="flex flex-wrap items-center gap-1.5">
        <Button
          type="button"
          size="sm"
          variant="secondary"
          className="h-7 px-2.5 text-xs"
          disabled={disabled}
          data-testid="category-suggestion-use"
          onClick={() => onAccept(suggestion.category_id)}
        >
          {t('transactions.useSuggestion', { category: suggestion.category_name })}
        </Button>
      </div>
    </div>
  )
}
