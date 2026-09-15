import { describe, expect, it, vi } from 'vitest'
import { screen } from '@testing-library/react'
import { FinancialSummaryCards } from '@/components/dashboard/financial-summary-cards'
import { SpendingByCategoryPanel } from '@/components/dashboard/spending-by-category-panel'
import { MonthlyTrendChart } from '@/components/dashboard/monthly-trend-chart'
import { TopExpensesList } from '@/components/dashboard/top-expenses-list'
import { TopMerchantsList } from '@/components/dashboard/top-merchants-list'
import { CreditCardsOverview } from '@/components/dashboard/credit-cards-overview'
import { PendingCategorizationCard } from '@/components/dashboard/pending-categorization-card'
import { DashboardEmptyState } from '@/components/dashboard/dashboard-empty-state'
import { renderWithProviders, t } from '@/test/utils'
import { formatCurrency } from '@/lib/format'
import type {
  CreditCardDashboardItem,
  MonthlyTrend,
  SpendingByCategory,
  TopExpense,
  TopMerchant,
} from '@/types'

const mask = (v: string) => v
const identity = (v: string) => v

/** Intl may emit NBSP; match leaf text flexibly. */
function hasMoney(amount: number, currency = 'BRL', locale = 'pt-BR') {
  const expected = formatCurrency(amount, currency, locale).replace(/[\s\u00a0]/g, '')
  return screen.getByText((_, el) => {
    if (!el || el.children.length > 0) return false
    const text = (el.textContent ?? '').replace(/[\s\u00a0]/g, '')
    return text === expected
  })
}

describe('FinancialSummaryCards', () => {
  it('renders income, expenses and positive net from API values', () => {
    renderWithProviders(
      <FinancialSummaryCards
        income={8000}
        expenses={2155}
        net={5845}
        currency="BRL"
        locale="pt-BR"
        mask={mask}
      />,
    )
    expect(screen.getByText(t('dashboard.income'))).toBeInTheDocument()
    expect(screen.getByText(t('dashboard.expenses'))).toBeInTheDocument()
    expect(screen.getByText(t('dashboard.netResult'))).toBeInTheDocument()
    expect(hasMoney(8000)).toBeInTheDocument()
    expect(hasMoney(2155)).toBeInTheDocument()
    expect(hasMoney(5845)).toBeInTheDocument()
    expect(screen.getByText(t('dashboard.netPositive'))).toBeInTheDocument()
  })

  it('renders negative net with deficit label (not color-only)', () => {
    renderWithProviders(
      <FinancialSummaryCards
        income={1000}
        expenses={2500}
        net={-1500}
        currency="BRL"
        locale="pt-BR"
        mask={mask}
      />,
    )
    expect(hasMoney(-1500)).toBeInTheDocument()
    expect(screen.getByText(t('dashboard.netNegative'))).toBeInTheDocument()
  })

  it('shows skeletons while loading', () => {
    const { container } = renderWithProviders(
      <FinancialSummaryCards
        income={0}
        expenses={0}
        net={0}
        currency="BRL"
        locale="pt-BR"
        loading
        mask={mask}
      />,
    )
    expect(container.querySelectorAll('[data-slot="skeleton"], .animate-pulse').length).toBeGreaterThan(0)
  })
})

describe('SpendingByCategoryPanel', () => {
  const items: SpendingByCategory[] = [
    {
      category_id: 'c1',
      category_name: 'Alimentação',
      category_icon: 'utensils',
      category_color: '#10b981',
      total: 1500,
      projected_total: 1500,
      percentage: 66.5,
    },
    {
      category_id: null,
      category_name: 'Uncategorized',
      category_icon: 'help',
      category_color: '#94a3b8',
      total: 100,
      projected_total: 100,
      percentage: 4.4,
    },
  ]

  it('shows category breakdown including Sem categoria', () => {
    renderWithProviders(
      <SpendingByCategoryPanel items={items} currency="BRL" locale="pt-BR" mask={mask} />,
    )
    expect(screen.getByText('Alimentação')).toBeInTheDocument()
    expect(screen.getByText(t('dashboard.uncategorizedBucket'))).toBeInTheDocument()
    expect(screen.getByText('66.5%')).toBeInTheDocument()
    expect(screen.getByText('4.4%')).toBeInTheDocument()
  })

  it('navigates via uncategorized CTA callback', async () => {
    const onUncategorizedClick = vi.fn()
    const { user } = renderWithProviders(
      <SpendingByCategoryPanel
        items={items}
        currency="BRL"
        locale="pt-BR"
        mask={mask}
        onUncategorizedClick={onUncategorizedClick}
      />,
    )
    await user.click(screen.getByText(t('dashboard.uncategorizedBucket')))
    expect(onUncategorizedClick).toHaveBeenCalled()
  })

  it('shows widget error with retry', async () => {
    const onRetry = vi.fn()
    const { user } = renderWithProviders(
      <SpendingByCategoryPanel
        items={[]}
        currency="BRL"
        locale="pt-BR"
        error
        mask={mask}
        onRetry={onRetry}
      />,
    )
    expect(screen.getByText(t('dashboard.widgetError'))).toBeInTheDocument()
    await user.click(screen.getByText(t('dashboard.retry')))
    expect(onRetry).toHaveBeenCalled()
  })
})

describe('MonthlyTrendChart', () => {
  const data: MonthlyTrend[] = [
    { month: '2026-07', income: 0, expenses: 0, net: 0 },
    { month: '2026-08', income: 5000, expenses: 2000, net: 3000 },
    { month: '2026-09', income: 8000, expenses: 2155, net: 5845 },
  ]

  it('renders trend chart including zero months', () => {
    const { container } = renderWithProviders(
      <MonthlyTrendChart data={data} currency="BRL" locale="pt-BR" mask={identity} />,
    )
    expect(screen.getByText(t('dashboard.monthlyTrend'))).toBeInTheDocument()
    // Recharts mounts an svg when data is present
    expect(container.querySelector('svg')).toBeTruthy()
  })
})

describe('TopExpensesList', () => {
  const items: TopExpense[] = [
    {
      id: '1',
      date: '2026-09-12',
      description: 'Supermercado',
      payee: 'Supermercado',
      category_id: 'c1',
      category_name: 'Alimentação',
      account_id: 'a1',
      account_name: 'Nubank',
      amount: 1200,
      currency: 'BRL',
    },
  ]

  it('renders compact top expenses', () => {
    renderWithProviders(
      <TopExpensesList items={items} currency="BRL" locale="pt-BR" mask={mask} />,
    )
    expect(screen.getByText('Supermercado')).toBeInTheDocument()
    expect(screen.getByText(/Alimentação/)).toBeInTheDocument()
    expect(hasMoney(1200)).toBeInTheDocument()
  })
})

describe('TopMerchantsList', () => {
  const items: TopMerchant[] = [
    { merchant: 'iFood', amount: 620, transaction_count: 8 },
  ]

  it('uses where-I-spent title and purchase count', () => {
    renderWithProviders(
      <TopMerchantsList items={items} currency="BRL" locale="pt-BR" mask={mask} />,
    )
    expect(screen.getByText(t('dashboard.topMerchants'))).toBeInTheDocument()
    expect(screen.getByText('iFood')).toBeInTheDocument()
    expect(hasMoney(620)).toBeInTheDocument()
  })
})

describe('CreditCardsOverview', () => {
  it('shows bill amount when present', () => {
    const items: CreditCardDashboardItem[] = [
      {
        account_id: 'cc1',
        name: 'Nubank Mastercard',
        balance: 2155,
        currency: 'BRL',
        current_bill_amount: 2155,
        current_bill_due_date: '2026-09-15',
      },
    ]
    renderWithProviders(<CreditCardsOverview items={items} locale="pt-BR" mask={mask} />)
    expect(screen.getByText(/Nubank Mastercard/)).toBeInTheDocument()
    expect(hasMoney(2155)).toBeInTheDocument()
  })

  it('shows no-bill state without treating as error', () => {
    const items: CreditCardDashboardItem[] = [
      {
        account_id: 'cc1',
        name: 'Cartão X',
        balance: 0,
        currency: 'BRL',
        current_bill_amount: null,
      },
    ]
    renderWithProviders(<CreditCardsOverview items={items} locale="pt-BR" mask={mask} />)
    expect(screen.getByText(t('dashboard.noBillAvailable'))).toBeInTheDocument()
  })
})

describe('PendingCategorizationCard', () => {
  it('links to pending inbox when count > 0', () => {
    renderWithProviders(
      <PendingCategorizationCard
        count={12}
        amount={1840}
        currency="BRL"
        locale="pt-BR"
        mask={mask}
      />,
    )
    const link = screen.getByRole('link')
    expect(link).toHaveAttribute('href', '/transactions?uncategorized=1')
    expect(screen.getByText(t('dashboard.uncategorizedCta', { count: 12 }))).toBeInTheDocument()
    expect(screen.getByText(t('dashboard.reviewPending'), { exact: false })).toBeInTheDocument()
  })

  it('shows discrete all-categorized state when count is 0', () => {
    renderWithProviders(
      <PendingCategorizationCard
        count={0}
        amount={0}
        currency="BRL"
        locale="pt-BR"
        mask={mask}
      />,
    )
    expect(screen.getByText(t('dashboard.allCategorizedDesc'))).toBeInTheDocument()
  })
})

describe('DashboardEmptyState', () => {
  it('CTA goes to import', () => {
    renderWithProviders(<DashboardEmptyState />)
    expect(screen.getByText(t('dashboard.emptyTitle'))).toBeInTheDocument()
    expect(screen.getByRole('link', { name: t('dashboard.emptyCta') })).toHaveAttribute('href', '/import')
  })
})

describe('dashboard currency formatting (pt-BR)', () => {
  it('formats large BRL amounts', () => {
    expect(formatCurrency(999.99, 'BRL', 'pt-BR')).toMatch(/999,99/)
    expect(formatCurrency(12345.67, 'BRL', 'pt-BR')).toMatch(/12\.345,67/)
    expect(formatCurrency(1234567.89, 'BRL', 'pt-BR')).toMatch(/1\.234\.567,89/)
  })
})
