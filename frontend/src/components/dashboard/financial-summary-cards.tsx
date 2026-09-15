import { useTranslation } from 'react-i18next'
import { Skeleton } from '@/components/ui/skeleton'
import { formatCurrency } from '@/lib/format'

type Props = {
  income: number
  expenses: number
  net: number
  currency: string
  locale: string
  loading?: boolean
  mask: (value: string) => string
  onIncomeClick?: () => void
  onExpensesClick?: () => void
}

export function FinancialSummaryCards({
  income,
  expenses,
  net,
  currency,
  locale,
  loading,
  mask,
  onIncomeClick,
  onExpensesClick,
}: Props) {
  const { t } = useTranslation()
  const netPositive = net > 0
  const netNegative = net < 0
  const netSignLabel = netPositive
    ? t('dashboard.netPositive')
    : netNegative
      ? t('dashboard.netNegative')
      : t('dashboard.netZero')

  const cards = [
    {
      key: 'income',
      label: t('dashboard.income'),
      value: income,
      className: 'text-emerald-600 dark:text-emerald-400',
      onClick: onIncomeClick,
      signHint: t('dashboard.incomeHint'),
      // Mobile priority: Result → Expenses → Income
      orderClass: 'order-3 sm:order-1',
    },
    {
      key: 'expenses',
      label: t('dashboard.expenses'),
      value: expenses,
      className: 'text-rose-600 dark:text-rose-400',
      onClick: onExpensesClick,
      signHint: t('dashboard.expensesHint'),
      orderClass: 'order-2',
    },
    {
      key: 'net',
      label: t('dashboard.netResult'),
      value: net,
      className: netNegative
        ? 'text-rose-600 dark:text-rose-400'
        : netPositive
          ? 'text-emerald-600 dark:text-emerald-400'
          : 'text-foreground',
      onClick: undefined,
      signHint: netSignLabel,
      orderClass: 'order-1 sm:order-3',
    },
  ] as const

  return (
    <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 gap-3 mb-5">
      {cards.map((card) => (
        <div
          key={card.key}
          className={`${card.orderClass} bg-card rounded-xl border border-border shadow-sm px-4 py-4 ${
            card.onClick ? 'cursor-pointer hover:bg-muted/40 transition-colors' : ''
          }`}
          onClick={card.onClick}
          onKeyDown={
            card.onClick
              ? (e) => {
                  if (e.key === 'Enter' || e.key === ' ') {
                    e.preventDefault()
                    card.onClick?.()
                  }
                }
              : undefined
          }
          role={card.onClick ? 'button' : undefined}
          tabIndex={card.onClick ? 0 : undefined}
        >
          <p className="text-xs font-semibold text-muted-foreground mb-1">{card.label}</p>
          {loading ? (
            <Skeleton className="h-8 w-32" />
          ) : (
            <>
              <p className={`text-2xl font-bold tabular-nums leading-tight ${card.className}`}>
                {mask(formatCurrency(card.value, currency, locale))}
              </p>
              <p className="text-[11px] text-muted-foreground mt-1">{card.signHint}</p>
            </>
          )}
        </div>
      ))}
    </div>
  )
}
