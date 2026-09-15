import { useTranslation } from 'react-i18next'
import { Skeleton } from '@/components/ui/skeleton'
import { CategoryIcon } from '@/components/category-icon'
import { formatCurrency } from '@/lib/format'
import type { SpendingByCategory } from '@/types'

type Props = {
  items: SpendingByCategory[]
  currency: string
  locale: string
  loading?: boolean
  error?: boolean
  mask: (value: string) => string
  onRetry?: () => void
  onCategoryClick?: (item: SpendingByCategory) => void
  onUncategorizedClick?: () => void
}

export function SpendingByCategoryPanel({
  items,
  currency,
  locale,
  loading,
  error,
  mask,
  onRetry,
  onCategoryClick,
  onUncategorizedClick,
}: Props) {
  const { t } = useTranslation()
  const max = Math.max(...items.map((i) => i.total), 1)

  return (
    <div className="bg-card rounded-xl border border-border shadow-sm flex flex-col min-h-[320px] max-h-[420px]">
      <div className="px-5 py-4 border-b border-border shrink-0">
        <p className="text-sm font-semibold text-foreground">{t('dashboard.spendingByCategory')}</p>
      </div>
      <div className="p-3 overflow-y-auto flex-1">
        {loading ? (
          <div className="space-y-3 p-2">
            {Array.from({ length: 4 }).map((_, i) => (
              <Skeleton key={i} className="h-12 w-full" />
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
          <div className="space-y-1.5">
            {items.map((item) => {
              const isUncategorized = item.category_id == null
              return (
                <button
                  key={item.category_id ?? 'uncategorized'}
                  type="button"
                  className="w-full rounded-lg px-3 py-2.5 hover:bg-muted/50 transition-colors text-left"
                  onClick={() => {
                    if (isUncategorized) onUncategorizedClick?.()
                    else onCategoryClick?.(item)
                  }}
                >
                  <div className="flex items-center gap-3">
                    <CategoryIcon
                      icon={item.category_icon}
                      color={item.category_color}
                      size="lg"
                    />
                    <div className="flex-1 min-w-0">
                      <div className="flex items-center justify-between gap-2 mb-1">
                        <span className="text-sm font-semibold text-foreground truncate">
                          {isUncategorized ? t('dashboard.uncategorizedBucket') : item.category_name}
                        </span>
                        <div className="flex items-center gap-2 shrink-0">
                          <span className="text-sm font-bold tabular-nums text-foreground">
                            {mask(formatCurrency(item.total, currency, locale))}
                          </span>
                          <span className="text-[11px] tabular-nums text-muted-foreground">
                            {item.percentage.toFixed(1)}%
                          </span>
                        </div>
                      </div>
                      <div className="h-1.5 bg-muted/60 rounded-full overflow-hidden">
                        <div
                          className="h-full rounded-full bg-muted-foreground/40"
                          style={{
                            width: `${Math.min((item.total / max) * 100, 100)}%`,
                            backgroundColor: item.category_color || undefined,
                          }}
                        />
                      </div>
                    </div>
                  </div>
                </button>
              )
            })}
          </div>
        )}
      </div>
    </div>
  )
}
