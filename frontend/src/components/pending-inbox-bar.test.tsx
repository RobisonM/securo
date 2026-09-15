import { describe, expect, it, vi } from 'vitest'
import { screen } from '@testing-library/react'
import { PendingInboxBar } from '@/components/pending-inbox-bar'
import { renderWithProviders, t } from '@/test/utils'

describe('PendingInboxBar', () => {
  it('toggles pending inbox and shows count', async () => {
    const onToggle = vi.fn()
    const { user, rerender } = renderWithProviders(
      <PendingInboxBar active={false} count={null} onToggle={onToggle} />,
    )

    expect(screen.getByTestId('pending-inbox-toggle')).toHaveTextContent(t('transactions.pendingInbox'))
    expect(screen.queryByTestId('pending-inbox-count')).not.toBeInTheDocument()

    await user.click(screen.getByTestId('pending-inbox-toggle'))
    expect(onToggle).toHaveBeenCalledWith(true)

    rerender(<PendingInboxBar active count={42} onToggle={onToggle} />)
    expect(screen.getByTestId('pending-inbox-count')).toHaveTextContent('42')
    expect(screen.getByText(t('transactions.pendingInboxHint'))).toBeInTheDocument()
  })
})
