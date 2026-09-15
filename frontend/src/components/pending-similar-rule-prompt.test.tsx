import { beforeEach, describe, expect, it, vi } from 'vitest'
import { screen, waitFor } from '@testing-library/react'
import { PendingSimilarRulePrompt } from '@/components/pending-similar-rule-prompt'
import { renderWithProviders, t } from '@/test/utils'

const api = vi.hoisted(() => ({
  rules: {
    preview: vi.fn(),
    create: vi.fn(),
  },
}))

vi.mock('@/lib/api', () => ({
  rules: api.rules,
}))

describe('PendingSimilarRulePrompt', () => {
  const onClose = vi.fn()
  const onConfirmCreate = vi.fn()
  const onOpenCustomRule = vi.fn()

  beforeEach(() => {
    vi.clearAllMocks()
    api.rules.preview.mockResolvedValue({
      matched: 12,
      will_change: 10,
      will_apply: true,
      sample: [
        { id: '1', description: 'IFOOD *1234', date: '2026-01-01', amount: 10, currency: 'BRL', type: 'debit', current_category_id: null, current_category_name: null, new_category_id: 'cat-1', new_category_name: 'Food', will_change: true },
        { id: '2', description: 'PIX QR CODE IFOOD', date: '2026-01-02', amount: 20, currency: 'BRL', type: 'debit', current_category_id: null, current_category_name: null, new_category_id: 'cat-1', new_category_name: 'Food', will_change: true },
      ],
      offset: 0,
    })
  })

  it('does not create a rule until the user opts in and confirms', async () => {
    const { user } = renderWithProviders(
      <PendingSimilarRulePrompt
        open
        onClose={onClose}
        description="PIX QR CODE IFOOD 123"
        categoryId="cat-1"
        categoryName="Food"
        conditionValue="IFOOD"
        isStable
        onConfirmCreate={onConfirmCreate}
        onOpenCustomRule={onOpenCustomRule}
      />,
    )

    expect(screen.getByTestId('pending-similar-rule-prompt')).toBeInTheDocument()
    expect(screen.getByText(t('transactions.transactionCategorized'))).toBeInTheDocument()
    expect(api.rules.preview).not.toHaveBeenCalled()
    expect(screen.queryByTestId('create-rule-and-apply')).not.toBeInTheDocument()

    await user.click(screen.getByTestId('apply-similar-checkbox'))

    await waitFor(() => expect(api.rules.preview).toHaveBeenCalled())
    expect(await screen.findByTestId('similar-match-count')).toHaveTextContent('12')
    expect(screen.getByText('IFOOD *1234')).toBeInTheDocument()

    await user.click(screen.getByTestId('create-rule-and-apply'))
    expect(onConfirmCreate).toHaveBeenCalledWith(
      expect.objectContaining({
        apply_to_existing: true,
        conditions: [{ field: 'description', op: 'contains', value: 'IFOOD' }],
        actions: [{ op: 'set_category', value: 'cat-1' }],
      }),
    )
  })

  it('cancel closes without creating a rule (categorization stays saved)', async () => {
    const { user } = renderWithProviders(
      <PendingSimilarRulePrompt
        open
        onClose={onClose}
        description="NETFLIX"
        categoryId="cat-1"
        conditionValue="NETFLIX"
        isStable
        onConfirmCreate={onConfirmCreate}
        onOpenCustomRule={onOpenCustomRule}
      />,
    )

    await user.click(screen.getByTestId('pending-similar-dismiss'))
    expect(onClose).toHaveBeenCalled()
    expect(onConfirmCreate).not.toHaveBeenCalled()
  })

  it('opens custom rule dialog when no stable pattern exists', async () => {
    const { user } = renderWithProviders(
      <PendingSimilarRulePrompt
        open
        onClose={onClose}
        description="PIX ENVIADO JOAO"
        categoryId="cat-1"
        conditionValue="PIX ENVIADO JOAO"
        isStable={false}
        onConfirmCreate={onConfirmCreate}
        onOpenCustomRule={onOpenCustomRule}
      />,
    )

    await user.click(screen.getByTestId('apply-similar-checkbox'))
    expect(screen.getByText(t('transactions.noStablePattern'))).toBeInTheDocument()
    await user.click(screen.getByRole('button', { name: t('transactions.createRule') }))
    expect(onOpenCustomRule).toHaveBeenCalled()
    expect(onConfirmCreate).not.toHaveBeenCalled()
    expect(api.rules.preview).not.toHaveBeenCalled()
  })
})
