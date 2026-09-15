import { useTranslation } from 'react-i18next'
import { Inbox } from 'lucide-react'
import { cn } from '@/lib/utils'

type PendingInboxBarProps = {
  active: boolean
  /** Count when known (pending view total, or dashboard pending_categorization). */
  count?: number | null
  onToggle: (next: boolean) => void
}

/**
 * Quick access to the uncategorized "inbox" on the Transactions page.
 * Uses the existing `uncategorized=true` filter — not a separate route.
 */
export function PendingInboxBar({ active, count, onToggle }: PendingInboxBarProps) {
  const { t } = useTranslation()
  const showCount = typeof count === 'number' && count >= 0

  return (
    <div
      className={cn(
        'mb-4 flex flex-wrap items-center gap-2 rounded-xl border px-3 py-2.5',
        active
          ? 'border-amber-200 bg-amber-50/80 dark:border-amber-500/30 dark:bg-amber-500/10'
          : 'border-border bg-card',
      )}
      data-testid="pending-inbox-bar"
    >
      <button
        type="button"
        onClick={() => onToggle(!active)}
        className={cn(
          'inline-flex items-center gap-2 rounded-lg px-3 py-1.5 text-sm font-medium transition-colors',
          active
            ? 'bg-amber-100 text-amber-900 dark:bg-amber-500/20 dark:text-amber-100'
            : 'bg-muted/60 text-foreground hover:bg-muted',
        )}
        aria-pressed={active}
        data-testid="pending-inbox-toggle"
      >
        <Inbox size={15} className="shrink-0" />
        <span>{t('transactions.pendingInbox')}</span>
        {showCount && (
          <span
            className={cn(
              'inline-flex min-w-5 items-center justify-center rounded-full px-1.5 text-[11px] font-semibold tabular-nums',
              active
                ? 'bg-amber-200/80 text-amber-950 dark:bg-amber-400/30 dark:text-amber-50'
                : 'bg-background text-muted-foreground',
            )}
            data-testid="pending-inbox-count"
          >
            {count}
          </span>
        )}
      </button>
      {active && (
        <p className="text-xs text-muted-foreground min-w-0 flex-1">
          {t('transactions.pendingInboxHint')}
        </p>
      )}
    </div>
  )
}
