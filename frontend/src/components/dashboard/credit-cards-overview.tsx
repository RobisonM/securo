import { Link } from 'react-router-dom'
import { useTranslation } from 'react-i18next'
import { CreditCard } from 'lucide-react'
import { Skeleton } from '@/components/ui/skeleton'
import { formatCurrency } from '@/lib/format'
import type { CreditCardDashboardItem } from '@/types'

type Props = {
  items: CreditCardDashboardItem[]
  locale: string
  loading?: boolean
  error?: boolean
  mask: (value: string) => string
  onRetry?: () => void
}

export function CreditCardsOverview({
  items,
  locale,
  loading,
  error,
  mask,
  onRetry,
}: Props) {
  const { t } = useTranslation()

  return (
    <div className="bg-card rounded-xl border border-border shadow-sm mb-5">
      <div className="px-5 py-4 border-b border-border">
        <p className="text-sm font-semibold text-foreground">{t('dashboard.creditCards')}</p>
      </div>
      <div className="p-4">
        {loading ? (
          <div className="grid grid-cols-1 sm:grid-cols-2 gap-3">
            {Array.from({ length: 2 }).map((_, i) => (
              <Skeleton key={i} className="h-28 w-full" />
            ))}
          </div>
        ) : error ? (
          <div className="flex flex-col items-center justify-center gap-2 py-8 text-center">
            <p className="text-sm text-muted-foreground">{t('dashboard.creditCardsError')}</p>
            {onRetry && (
              <button type="button" className="text-sm font-medium text-primary hover:underline" onClick={onRetry}>
                {t('dashboard.retry')}
              </button>
            )}
          </div>
        ) : items.length === 0 ? (
          <p className="text-sm text-muted-foreground py-6 text-center">{t('dashboard.noCreditCards')}</p>
        ) : (
          <div className="grid grid-cols-1 sm:grid-cols-2 xl:grid-cols-3 gap-3">
            {items.map((card) => {
              const due = card.current_bill_due_date || card.next_due_date
              const dueLabel = due
                ? new Date(`${due}T00:00:00`).toLocaleDateString(locale)
                : null
              return (
                <Link
                  key={card.account_id}
                  to={`/accounts/${card.account_id}`}
                  className="rounded-lg border border-border bg-background px-4 py-3 hover:border-foreground/25 transition-colors focus:outline-none focus-visible:ring-ring/30 focus-visible:ring-[2px]"
                >
                  <div className="flex items-center gap-2 mb-2">
                    <CreditCard size={16} className="text-muted-foreground shrink-0" />
                    <p className="text-sm font-semibold text-foreground truncate">
                      {card.name}
                      {card.card_brand ? ` · ${card.card_brand}` : ''}
                    </p>
                  </div>
                  {card.current_bill_amount != null ? (
                    <p className="text-lg font-bold tabular-nums text-foreground">
                      {mask(formatCurrency(card.current_bill_amount, card.currency, locale))}
                    </p>
                  ) : (
                    <p className="text-sm text-muted-foreground">{t('dashboard.noBillAvailable')}</p>
                  )}
                  {dueLabel && (
                    <p className="text-xs text-muted-foreground mt-1">
                      {t('dashboard.dueDate')}: {dueLabel}
                    </p>
                  )}
                  {card.available_credit != null && card.credit_limit != null && (
                    <p className="text-xs text-muted-foreground mt-1">
                      {t('dashboard.availableLimit')}:{' '}
                      {mask(formatCurrency(card.available_credit, card.currency, locale))}
                    </p>
                  )}
                </Link>
              )
            })}
          </div>
        )}
      </div>
    </div>
  )
}
