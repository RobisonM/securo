import { Link } from 'react-router-dom'
import { useTranslation } from 'react-i18next'
import { AlertCircle, CheckCircle2 } from 'lucide-react'
import { formatCurrency } from '@/lib/format'

type Props = {
  count: number
  amount: number
  currency: string
  locale: string
  loading?: boolean
  mask: (value: string) => string
}

export function PendingCategorizationCard({
  count,
  amount,
  currency,
  locale,
  loading,
  mask,
}: Props) {
  const { t } = useTranslation()
  if (loading) return null

  if (count <= 0) {
    return (
      <div className="flex items-center gap-2 bg-emerald-50 dark:bg-emerald-500/10 border border-emerald-200 dark:border-emerald-500/30 rounded-lg px-4 py-2.5 mb-5">
        <CheckCircle2 className="w-4 h-4 text-emerald-500 shrink-0" aria-hidden />
        <span className="text-sm text-emerald-900 dark:text-emerald-200">
          {t('dashboard.allCategorizedDesc')}
        </span>
      </div>
    )
  }

  return (
    <Link
      to="/transactions?uncategorized=1"
      className="w-full flex items-center justify-between gap-3 bg-amber-50 dark:bg-amber-500/10 border border-amber-200 dark:border-amber-500/30 rounded-lg px-4 py-2.5 mb-5 hover:bg-amber-100 dark:hover:bg-amber-500/20 transition-colors focus:outline-none focus-visible:ring-ring/30 focus-visible:ring-[2px]"
    >
      <div className="flex items-center gap-2.5 min-w-0">
        <AlertCircle size={16} className="shrink-0 text-amber-600 dark:text-amber-400" aria-hidden />
        <div className="min-w-0">
          <p className="text-sm text-amber-900 dark:text-amber-200 truncate">
            {t('dashboard.uncategorizedCta', { count })}
          </p>
          {amount > 0 && (
            <p className="text-xs text-amber-700/80 dark:text-amber-300/80">
              {t('dashboard.uncategorizedTotal', {
                amount: mask(formatCurrency(amount, currency, locale)),
              })}
            </p>
          )}
        </div>
      </div>
      <span className="shrink-0 text-sm font-semibold text-amber-600 dark:text-amber-400">
        {t('dashboard.reviewPending')} &rarr;
      </span>
    </Link>
  )
}
