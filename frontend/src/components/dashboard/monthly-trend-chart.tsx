import { useMemo } from 'react'
import { useTranslation } from 'react-i18next'
import {
  Bar,
  BarChart,
  CartesianGrid,
  Legend,
  ResponsiveContainer,
  Tooltip as RechartsTooltip,
  XAxis,
  YAxis,
} from 'recharts'
import { Skeleton } from '@/components/ui/skeleton'
import { formatCurrency } from '@/lib/format'
import type { MonthlyTrend } from '@/types'

type Props = {
  data: MonthlyTrend[]
  currency: string
  locale: string
  loading?: boolean
  error?: boolean
  mask: (value: string) => string
  onRetry?: () => void
}

function shortMonth(ym: string, locale: string): string {
  const [y, m] = ym.split('-').map(Number)
  const d = new Date(y, (m || 1) - 1, 1)
  return d.toLocaleDateString(locale, { month: 'short' })
}

export function MonthlyTrendChart({
  data,
  currency,
  locale,
  loading,
  error,
  mask,
  onRetry,
}: Props) {
  const { t } = useTranslation()
  const chartData = useMemo(
    () =>
      data.map((row) => ({
        ...row,
        label: shortMonth(row.month, locale),
        net: row.net ?? row.income - row.expenses,
      })),
    [data, locale],
  )

  return (
    <div className="bg-card rounded-xl border border-border shadow-sm flex flex-col min-h-[320px]">
      <div className="px-5 py-4 border-b border-border shrink-0">
        <p className="text-sm font-semibold text-foreground">{t('dashboard.monthlyTrend')}</p>
      </div>
      <div className="p-4 flex-1 min-h-[260px]">
        {loading ? (
          <Skeleton className="h-full w-full min-h-[220px]" />
        ) : error ? (
          <div className="flex flex-col items-center justify-center gap-2 h-full text-center">
            <p className="text-sm text-muted-foreground">{t('dashboard.widgetError')}</p>
            {onRetry && (
              <button type="button" className="text-sm font-medium text-primary hover:underline" onClick={onRetry}>
                {t('dashboard.retry')}
              </button>
            )}
          </div>
        ) : chartData.length === 0 ? (
          <div className="flex items-center justify-center h-full">
            <p className="text-sm text-muted-foreground">{t('dashboard.noPeriodActivity')}</p>
          </div>
        ) : (
          <ResponsiveContainer width="100%" height="100%" minHeight={220}>
            <BarChart data={chartData} margin={{ top: 8, right: 8, left: 0, bottom: 0 }}>
              <CartesianGrid strokeDasharray="3 3" className="stroke-border" />
              <XAxis dataKey="label" tick={{ fontSize: 11 }} />
              <YAxis tick={{ fontSize: 11 }} width={48} />
              <RechartsTooltip
                formatter={(value, name) => {
                  const n = typeof value === 'number' ? value : Number(value ?? 0)
                  const key =
                    name === 'income'
                      ? t('dashboard.income')
                      : name === 'expenses'
                        ? t('dashboard.expenses')
                        : t('dashboard.netResult')
                  return [mask(formatCurrency(n, currency, locale)), key]
                }}
                labelFormatter={(_, payload) => {
                  const row = payload?.[0]?.payload as MonthlyTrend | undefined
                  return row?.month ?? ''
                }}
              />
              <Legend
                formatter={(value) =>
                  value === 'income'
                    ? t('dashboard.income')
                    : value === 'expenses'
                      ? t('dashboard.expenses')
                      : t('dashboard.netResult')
                }
              />
              <Bar dataKey="income" fill="var(--color-emerald-500, #10b981)" radius={[3, 3, 0, 0]} name="income" />
              <Bar dataKey="expenses" fill="var(--color-rose-500, #f43f5e)" radius={[3, 3, 0, 0]} name="expenses" />
            </BarChart>
          </ResponsiveContainer>
        )}
      </div>
    </div>
  )
}
