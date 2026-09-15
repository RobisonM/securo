import { describe, expect, it, vi } from 'vitest'
import { screen } from '@testing-library/react'
import { CategorySuggestionActions } from '@/components/category-suggestion-actions'
import { renderWithProviders, t } from '@/test/utils'
import type { CategorySuggestion } from '@/types'

const suggestion: CategorySuggestion = {
  category_id: 'cat-food',
  category_name: 'Alimentação',
  reason: '2 of 2 recent transactions for IFOOD were Alimentação',
  reason_code: 'same_merchant',
  matched_count: 2,
  total_count: 2,
  confidence: 1,
  identity_label: 'IFOOD',
}

describe('CategorySuggestionActions', () => {
  it('shows suggestion label, count reason, and accepts without auto-applying', async () => {
    const onAccept = vi.fn()
    const { user } = renderWithProviders(
      <CategorySuggestionActions suggestion={suggestion} onAccept={onAccept} />,
    )

    expect(screen.getByTestId('category-suggestion')).toHaveTextContent(
      t('transactions.suggestionLabel'),
    )
    expect(screen.getByTestId('category-suggestion')).toHaveTextContent('Alimentação')
    expect(screen.getByTestId('category-suggestion')).toHaveTextContent(
      t('transactions.suggestionReasonMerchant', {
        matched: 2,
        total: 2,
        category: 'Alimentação',
        merchant: 'IFOOD',
      }),
    )
    expect(screen.getByTestId('category-suggestion')).toHaveAttribute(
      'title',
      t('transactions.suggestionBasedOnMerchant', { merchant: 'IFOOD' }),
    )

    await user.click(screen.getByTestId('category-suggestion-use'))
    expect(onAccept).toHaveBeenCalledWith('cat-food')
  })
})
