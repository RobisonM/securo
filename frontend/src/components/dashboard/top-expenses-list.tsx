import { useTranslation } from 'react-i18next'
import { Skeleton } from '@/components/ui/skeleton'
import { formatCurrency } from '@/lib/format'
import type { TopExpense } from '@/types'

type Props = {
  items: TopExpense[]
  currency: string
  locale: string
  loading?: boolean
  error?: boolean
  mask: (value: string) => string
  onRetry?: () => void
}

export function TopExpensesList({
  items,
  currency,
  locale,
  loading,
  error,
  mask,
  onRetry,
}: Props) {
  const { t } = useTranslation()

  return (
    <div className="bg-card rounded-xl border border-border shadow-sm flex flex-col min-h-[280px]">
      <div className="px-5 py-4 border-b border-border">
        <p className="text-sm font-semibold text-foreground">{t('dashboard.topExpenses')}</p>
      </div>
      <div className="p-2 flex-1">
        {loading ? (
          <div className="space-y-2 p-2">
            {Array.from({ length: 4 }).map((_, i) => (
              <Skeleton key={i} className="h-14 w-full" />
            ))}
          </div>
        ) : error ? (
          <div className="flex flex-col items-center justify-center gap-2 py-10 text-center px-4">
            <p className="text-sm text-muted-foreground">{t('dashboard.widgetError')}</p>
            {onRetry && (
              <button type="button" className="text-sm font-medium text-primary hover:underline" onClick={onRetry}>
                {t('dashboard.retry')}
              </button>
            )}
          </div>
        ) : items.length === 0 ? (
          <div className="flex items-center justify-center py-10">
            <p className="text-sm text-muted-foreground">{t('dashboard.noPeriodActivity')}</p>
          </div>
        ) : (
          <ul className="divide-y divide-border">
            {items.map((item) => {
              const title = item.payee || item.description
              const dateLabel = new Date(`${item.date}T00:00:00`).toLocaleDateString(locale, {
                day: '2-digit',
                month: 'short',
              })
              return (
                <li key={item.id} className="px-3 py-3 flex items-start justify-between gap-3">
                  <div className="min-w-0">
                    <p className="text-sm font-semibold text-foreground truncate">{title}</p>
                    <p className="text-xs text-muted-foreground truncate">
                      {item.category_name || t('dashboard.uncategorizedBucket')}
                      <span className="mx-1">·</span>
                      {dateLabel}
                    </p>
                  </div>
                  <p className="text-sm font-bold tabular-nums text-rose-600 dark:text-rose-400 shrink-0">
                    {mask(formatCurrency(item.amount, item.currency || currency, locale))}
                  </p>
                </li>
              )
            })}
          </ul>
        )}
      </div>
    </div>
  )
}
