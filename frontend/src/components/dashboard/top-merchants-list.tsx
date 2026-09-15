import { useTranslation } from 'react-i18next'
import { Skeleton } from '@/components/ui/skeleton'
import { formatCurrency } from '@/lib/format'
import type { TopMerchant } from '@/types'

type Props = {
  items: TopMerchant[]
  currency: string
  locale: string
  loading?: boolean
  error?: boolean
  mask: (value: string) => string
  onRetry?: () => void
}

export function TopMerchantsList({
  items,
  currency,
  locale,
  loading,
  error,
  mask,
  onRetry,
}: Props) {
  const { t } = useTranslation()
  const max = Math.max(...items.map((i) => i.amount), 1)

  return (
    <div className="bg-card rounded-xl border border-border shadow-sm flex flex-col min-h-[280px]">
      <div className="px-5 py-4 border-b border-border">
        <p className="text-sm font-semibold text-foreground">{t('dashboard.topMerchants')}</p>
      </div>
      <div className="p-3 flex-1">
        {loading ? (
          <div className="space-y-2 p-2">
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
          <div className="space-y-2">
            {items.map((item) => (
              <div key={item.merchant} className="px-2 py-2">
                <div className="flex items-center justify-between gap-2 mb-1">
                  <div className="min-w-0">
                    <p className="text-sm font-semibold text-foreground truncate">{item.merchant}</p>
                    <p className="text-[11px] text-muted-foreground">
                      {t('dashboard.purchaseCount', { count: item.transaction_count })}
                    </p>
                  </div>
                  <p className="text-sm font-bold tabular-nums shrink-0">
                    {mask(formatCurrency(item.amount, currency, locale))}
                  </p>
                </div>
                <div className="h-1.5 bg-muted/60 rounded-full overflow-hidden">
                  <div
                    className="h-full rounded-full bg-primary/70"
                    style={{ width: `${Math.min((item.amount / max) * 100, 100)}%` }}
                  />
                </div>
              </div>
            ))}
          </div>
        )}
      </div>
    </div>
  )
}
