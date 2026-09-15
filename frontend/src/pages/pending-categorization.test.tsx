import { beforeEach, describe, expect, it, vi } from 'vitest'
import { screen, waitFor, within } from '@testing-library/react'
import TransactionsPage from '@/pages/transactions'
import { renderWithProviders, t } from '@/test/utils'
import type { CategorySuggestion, Transaction } from '@/types'

const sampleSuggestion: CategorySuggestion = {
  category_id: 'cat-food',
  category_name: 'Alimentação',
  reason: '2 of 2 recent transactions for IFOOD were Alimentação',
  reason_code: 'same_merchant',
  matched_count: 2,
  total_count: 2,
  confidence: 1,
  identity_label: 'IFOOD',
}

const sampleTx = {
  id: 'tx-1',
  user_id: 'u1',
  account_id: 'acc-1',
  category_id: null,
  category: null,
  external_id: null,
  description: 'PIX QR CODE IFOOD 123456789',
  original_description: null,
  amount: 42.5,
  currency: 'BRL',
  date: '2026-03-01',
  type: 'debit' as const,
  source: 'import',
  status: 'posted' as const,
  payee: null,
  payee_id: null,
  payee_name: null,
  notes: null,
  transfer_pair_id: null,
  amount_primary: null,
  fx_rate_used: null,
  fx_fallback: false,
  installment_number: null,
  total_installments: null,
  installment_total_amount: null,
  installment_purchase_date: null,
  installment_series_id: null,
  bill_id: null,
  effective_bill_date: null,
  splits: [],
  is_ignored: false,
  exclude_from_pnl: false,
  classification: 'uncertain' as const,
  category_suggestion: null as CategorySuggestion | null,
} satisfies Partial<Transaction> & { id: string; description: string; classification: 'uncertain' }

const categories = [
  {
    id: 'cat-food',
    user_id: 'u1',
    name: 'Alimentação',
    type: 'expense',
    icon: null,
    color: '#f00',
    group_id: null,
    is_system: false,
    parent_id: null,
  },
]

const accounts = [
  {
    id: 'acc-1',
    user_id: 'u1',
    name: 'Nubank',
    type: 'checking',
    currency: 'BRL',
    balance: 0,
    institution: null,
    color: null,
    icon: null,
    is_archived: false,
    exclude_from_total: false,
  },
]

const api = vi.hoisted(() => ({
  transactions: {
    list: vi.fn(),
    update: vi.fn(),
    bulkCategorize: vi.fn(),
    bulkAddTags: vi.fn(),
    bulkRemoveTags: vi.fn(),
    bulkAddToGroup: vi.fn(),
    bulkDelete: vi.fn(),
    calendar: vi.fn(),
    create: vi.fn(),
    delete: vi.fn(),
    createTransfer: vi.fn(),
    linkTransfer: vi.fn(),
    unlinkTransfer: vi.fn(),
    createTransferCounterpart: vi.fn(),
    attachments: { list: vi.fn(), upload: vi.fn() },
  },
  categories: { list: vi.fn() },
  categoryGroups: { list: vi.fn() },
  accounts: { list: vi.fn() },
  recurring: { list: vi.fn() },
  payees: { list: vi.fn() },
  admin: {},
  groups: { list: vi.fn(), get: vi.fn() },
  rules: { list: vi.fn(), create: vi.fn(), preview: vi.fn() },
  reconciliation: { listSuggestions: vi.fn() },
}))

vi.mock('@/lib/api', () => api)

vi.mock('@/lib/page-chat-context', () => ({
  useRegisterPageChatContext: () => {},
}))

vi.mock('@/hooks/use-display-locale', () => ({
  useDisplayLocale: () => 'pt-BR',
  useDateLocale: () => 'pt-BR',
}))

vi.mock('@/hooks/use-mobile', () => ({
  useIsMobile: () => false,
}))

vi.mock('@/hooks/use-privacy-mode', () => ({
  usePrivacyMode: () => ({ mask: (v: string) => v }),
}))

vi.mock('@/contexts/auth-context', () => ({
  useAuth: () => ({ user: { preferences: { currency_display: 'BRL' } } }),
}))

vi.mock('@/contexts/workspace-context', () => ({
  useWorkspace: () => ({ canWrite: true, hasModule: () => false }),
}))

vi.mock('@/contexts/collection-filter-context', () => ({
  useCollectionFilter: () => ({ activeAccountIds: null }),
}))

vi.mock('sonner', () => ({
  toast: { success: vi.fn(), error: vi.fn() },
}))

function mockList(items: typeof sampleTx[] = [sampleTx], total = items.length) {
  api.transactions.list.mockResolvedValue({
    items,
    total,
    page: 1,
    limit: 20,
    pages: 1,
    summary: {
      income: 0,
      expense: total > 0 ? 42.5 : 0,
      net: total > 0 ? -42.5 : 0,
      excluded: 0,
      currency: 'BRL',
    },
  })
}

describe('Transactions pending categorization inbox', () => {
  beforeEach(() => {
    vi.clearAllMocks()
    mockList()
    api.categories.list.mockResolvedValue(categories)
    api.categoryGroups.list.mockResolvedValue([])
    api.accounts.list.mockResolvedValue(accounts)
    api.recurring.list.mockResolvedValue([])
    api.payees.list.mockResolvedValue([])
    api.groups.list.mockResolvedValue([])
    api.rules.list.mockResolvedValue([])
    api.rules.preview.mockResolvedValue({
      matched: 3,
      will_change: 3,
      will_apply: true,
      sample: [
        { ...sampleTx, id: 'a', description: 'IFOOD *1', current_category_id: null, current_category_name: null, new_category_id: 'cat-food', new_category_name: 'Alimentação', will_change: true },
      ],
      offset: 0,
    })
    api.rules.create.mockResolvedValue({ id: 'rule-1', applied_count: 2 })
    api.transactions.update.mockResolvedValue({ ...sampleTx, category_id: 'cat-food' })
    api.transactions.bulkCategorize.mockResolvedValue({ updated: 2 })
    api.reconciliation.listSuggestions.mockResolvedValue([])
  })

  it('loads uncategorized=true and renders pending rows with counter', async () => {
    renderWithProviders(<TransactionsPage />, { route: '/transactions?uncategorized=1' })

    await screen.findByText('PIX QR CODE IFOOD 123456789')
    await waitFor(() => {
      expect(api.transactions.list).toHaveBeenCalledWith(
        expect.objectContaining({ uncategorized: true, include_suggestions: true }),
      )
    })
    expect(screen.getByTestId('pending-inbox-toggle')).toHaveAttribute('aria-pressed', 'true')
    expect(screen.getByTestId('pending-inbox-count')).toHaveTextContent('1')
    expect(screen.getByText('Nubank')).toBeInTheDocument()
  })

  it('shows historical suggestion and Use categorizes via PATCH', async () => {
    mockList([{ ...sampleTx, category_suggestion: sampleSuggestion }], 1)
    let categorized = false
    api.transactions.list.mockImplementation(async () => ({
      items: categorized ? [] : [{ ...sampleTx, category_suggestion: sampleSuggestion }],
      total: categorized ? 0 : 1,
      page: 1,
      limit: 20,
      pages: 1,
      summary: {
        income: 0,
        expense: categorized ? 0 : 42.5,
        net: categorized ? 0 : -42.5,
        excluded: 0,
        currency: 'BRL',
      },
    }))
    api.transactions.update.mockImplementation(async () => {
      categorized = true
      return { ...sampleTx, category_id: 'cat-food', category_suggestion: null }
    })

    const { user } = renderWithProviders(<TransactionsPage />, {
      route: '/transactions?uncategorized=1',
    })

    expect(await screen.findByTestId('category-suggestion')).toBeInTheDocument()
    await user.click(screen.getByTestId('category-suggestion-use'))

    await waitFor(() => {
      expect(api.transactions.update).toHaveBeenCalledWith('tx-1', { category_id: 'cat-food' })
    })
    await waitFor(() => {
      expect(screen.queryByTestId('category-suggestion')).not.toBeInTheDocument()
    })
    // Accepting a suggestion still opens the similar-rule prompt (Epic 2C), not auto-rule.
    expect(await screen.findByTestId('pending-similar-rule-prompt')).toBeInTheDocument()
  })

  it('keeps pending flow when API returns no suggestion', async () => {
    mockList([{ ...sampleTx, category_suggestion: null }], 1)
    renderWithProviders(<TransactionsPage />, { route: '/transactions?uncategorized=1' })
    await screen.findByText('PIX QR CODE IFOOD 123456789')
    expect(screen.queryByTestId('category-suggestion')).not.toBeInTheDocument()
    expect(screen.getAllByRole('button', {
      name: new RegExp(t('transactions.selectCategory'), 'i'),
    }).length).toBeGreaterThan(0)
  })

  it('categorizes inline via PATCH and offers similar-rule preview', async () => {
    const { toast } = await import('sonner')
    let categorized = false
    api.transactions.list.mockImplementation(async () => ({
      items: categorized ? [] : [sampleTx],
      total: categorized ? 0 : 1,
      page: 1,
      limit: 20,
      pages: 1,
      summary: {
        income: 0,
        expense: categorized ? 0 : 42.5,
        net: categorized ? 0 : -42.5,
        excluded: 0,
        currency: 'BRL',
      },
    }))
    api.transactions.update.mockImplementation(async () => {
      categorized = true
      return { ...sampleTx, category_id: 'cat-food' }
    })

    const { user } = renderWithProviders(<TransactionsPage />, {
      route: '/transactions?uncategorized=1',
    })

    await screen.findByText('PIX QR CODE IFOOD 123456789')

    // Open category select and pick Alimentação
    const categoryTriggers = screen.getAllByRole('button', {
      name: new RegExp(t('transactions.selectCategory'), 'i'),
    })
    await user.click(categoryTriggers[0])
    await user.click(await screen.findByText('Alimentação'))

    await waitFor(() => {
      expect(api.transactions.update).toHaveBeenCalledWith('tx-1', { category_id: 'cat-food' })
    })

    expect(await screen.findByTestId('pending-similar-rule-prompt')).toBeInTheDocument()
    expect(toast.success).not.toHaveBeenCalledWith(t('transactions.updated'))

    // Opt into similar rule → preview required
    await user.click(screen.getByTestId('apply-similar-checkbox'))
    await waitFor(() => expect(api.rules.preview).toHaveBeenCalled())
    expect(await screen.findByTestId('similar-match-count')).toBeInTheDocument()

    await user.click(screen.getByTestId('create-rule-and-apply'))
    await waitFor(() => {
      expect(api.rules.create).toHaveBeenCalledWith(
        expect.objectContaining({
          apply_to_existing: true,
          conditions: [{ field: 'description', op: 'contains', value: 'IFOOD' }],
          actions: [{ op: 'set_category', value: 'cat-food' }],
        }),
      )
    })
  })

  it('keeps categorization when rule creation fails', async () => {
    const { toast } = await import('sonner')
    api.rules.create.mockRejectedValue({ response: { status: 500 } })

    const { user } = renderWithProviders(<TransactionsPage />, {
      route: '/transactions?uncategorized=1',
    })
    await screen.findByText('PIX QR CODE IFOOD 123456789')

    const categoryTriggers = screen.getAllByRole('button', {
      name: new RegExp(t('transactions.selectCategory'), 'i'),
    })
    await user.click(categoryTriggers[0])
    await user.click(await screen.findByText('Alimentação'))

    await screen.findByTestId('pending-similar-rule-prompt')
    await user.click(screen.getByTestId('apply-similar-checkbox'))
    await screen.findByTestId('create-rule-and-apply')
    await user.click(screen.getByTestId('create-rule-and-apply'))

    await waitFor(() => {
      expect(toast.error).toHaveBeenCalledWith(t('transactions.ruleCreateFailedAfterCategorize'))
    })
    // PATCH already happened and is not rolled back
    expect(api.transactions.update).toHaveBeenCalled()
  })

  it('restores row visibility when PATCH fails', async () => {
    const { toast } = await import('sonner')
    api.transactions.update.mockRejectedValue({ response: { data: { detail: 'boom' } } })

    const { user } = renderWithProviders(<TransactionsPage />, {
      route: '/transactions?uncategorized=1',
    })
    await screen.findByText('PIX QR CODE IFOOD 123456789')

    const categoryTriggers = screen.getAllByRole('button', {
      name: new RegExp(t('transactions.selectCategory'), 'i'),
    })
    await user.click(categoryTriggers[0])
    await user.click(await screen.findByText('Alimentação'))

    await waitFor(() => expect(toast.error).toHaveBeenCalled())
    expect(screen.getByText('PIX QR CODE IFOOD 123456789')).toBeInTheDocument()
    expect(screen.queryByTestId('pending-similar-rule-prompt')).not.toBeInTheDocument()
  })

  it('bulk categorizes selected rows without creating a rule', async () => {
    const tx2 = { ...sampleTx, id: 'tx-2', description: 'NETFLIX MAR' }
    mockList([sampleTx, tx2], 2)

    const { user } = renderWithProviders(<TransactionsPage />, {
      route: '/transactions?uncategorized=1',
    })
    await screen.findByText('PIX QR CODE IFOOD 123456789')
    await screen.findByText('NETFLIX MAR')

    const checkboxes = screen.getAllByRole('checkbox')
    // first is select-all header
    await user.click(checkboxes[1])
    await user.click(checkboxes[2])

    const bulkBar = screen.getByText(t('transactions.selected')).closest('div')?.parentElement
    expect(bulkBar).toBeTruthy()
    // CategorySelect in bulk bar
    const bulkCategory = within(document.body).getAllByRole('button', {
      name: new RegExp(t('transactions.selectCategory'), 'i'),
    })
    // Last trigger is typically the bulk bar one when rows also have selects
    await user.click(bulkCategory[bulkCategory.length - 1])
    await user.click(await screen.findByText('Alimentação'))

    await waitFor(() => {
      expect(api.transactions.bulkCategorize).toHaveBeenCalledWith(
        expect.arrayContaining(['tx-1', 'tx-2']),
        'cat-food',
      )
    })
    expect(api.rules.create).not.toHaveBeenCalled()
  })

  it('shows pending empty state', async () => {
    mockList([], 0)
    renderWithProviders(<TransactionsPage />, { route: '/transactions?uncategorized=1' })
    expect(await screen.findByTestId('transactions-empty')).toHaveTextContent(
      t('transactions.pendingEmpty'),
    )
  })

  it('shows API error state', async () => {
    api.transactions.list.mockRejectedValue(new Error('network'))
    renderWithProviders(<TransactionsPage />, { route: '/transactions?uncategorized=1' })
    expect(await screen.findByTestId('transactions-error')).toBeInTheDocument()
  })

  it('exposes pt-BR pending inbox copy', async () => {
    const i18n = (await import('@/lib/i18n')).default
    await i18n.changeLanguage('pt-BR')
    renderWithProviders(<TransactionsPage />, { route: '/transactions' })
    expect(await screen.findByTestId('pending-inbox-toggle')).toHaveTextContent('Pendentes')
    await i18n.changeLanguage('en')
  })
})
