import { useState } from 'react'
import { useTranslation } from 'react-i18next'
import { useQuery } from '@tanstack/react-query'
import { rules as rulesApi } from '@/lib/api'
import { Button } from '@/components/ui/button'
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from '@/components/ui/dialog'
import { Label } from '@/components/ui/label'
import { Switch } from '@/components/ui/switch'
import type { RuleAction, RuleCondition } from '@/types'

export type PendingSimilarRulePromptProps = {
  open: boolean
  onClose: () => void
  description: string
  categoryId: string
  categoryName?: string
  /** Proposed `contains` value (stable term or full description). */
  conditionValue: string
  isStable: boolean
  onConfirmCreate: (payload: {
    name: string
    conditions: RuleCondition[]
    actions: RuleAction[]
    apply_to_existing: boolean
  }) => void
  onOpenCustomRule: () => void
  creating?: boolean
}

/**
 * Post-categorize prompt: optionally create a rule for similar rows.
 * Preview is mandatory before create; never auto-checked.
 * Parent should unmount this when closed so local opt-in state resets.
 */
export function PendingSimilarRulePrompt({
  open,
  onClose,
  description,
  categoryId,
  categoryName,
  conditionValue,
  isStable,
  onConfirmCreate,
  onOpenCustomRule,
  creating = false,
}: PendingSimilarRulePromptProps) {
  const { t } = useTranslation()
  const [wantRule, setWantRule] = useState(false)

  const conditions: RuleCondition[] = [
    { field: 'description', op: 'contains', value: conditionValue },
  ]
  const actions: RuleAction[] = [{ op: 'set_category', value: categoryId }]

  const previewQuery = useQuery({
    queryKey: ['rule-preview', 'pending-similar', conditionValue, categoryId],
    queryFn: () =>
      rulesApi.preview({
        conditions_op: 'and',
        conditions,
        actions,
        is_active: true,
        apply_to_existing: true,
        overwrite_existing_categories: false,
        limit: 5,
        offset: 0,
      }),
    enabled: open && wantRule && isStable && !!conditionValue,
  })

  const matched = previewQuery.data?.matched ?? 0
  const samples = previewQuery.data?.sample ?? []

  const handleCreate = () => {
    const name = categoryName
      ? `${categoryName}: ${conditionValue}`
      : conditionValue
    onConfirmCreate({
      name: name.slice(0, 120),
      conditions,
      actions,
      apply_to_existing: true,
    })
  }

  return (
    <Dialog open={open} onOpenChange={(next) => { if (!next) onClose() }}>
      <DialogContent className="sm:max-w-md" data-testid="pending-similar-rule-prompt">
        <DialogHeader>
          <DialogTitle>{t('transactions.transactionCategorized')}</DialogTitle>
          <DialogDescription className="truncate">
            {description}
          </DialogDescription>
        </DialogHeader>

        <div className="space-y-4 py-1">
          <div className="flex items-center justify-between gap-3">
            <div className="space-y-1 min-w-0">
              <Label htmlFor="apply-similar" className="font-medium leading-snug cursor-pointer">
                {t('transactions.applyToSimilar')}
              </Label>
              <p className="text-xs text-muted-foreground">
                {t('transactions.applyToSimilarHint')}
              </p>
            </div>
            <Switch
              id="apply-similar"
              checked={wantRule}
              onCheckedChange={setWantRule}
              data-testid="apply-similar-checkbox"
            />
          </div>

          {wantRule && (
            <div className="rounded-md border bg-muted/30 p-3 space-y-2 text-sm">
              {!isStable ? (
                <p className="text-muted-foreground">{t('transactions.noStablePattern')}</p>
              ) : (
                <>
                  <p>
                    <span className="text-muted-foreground">{t('transactions.descriptionContains')}: </span>
                    <span className="font-mono font-medium">{conditionValue}</span>
                  </p>
                  {previewQuery.isLoading && (
                    <p className="text-muted-foreground">{t('common.loading')}</p>
                  )}
                  {previewQuery.isError && (
                    <p className="text-destructive">{t('common.error')}</p>
                  )}
                  {previewQuery.isSuccess && (
                    <>
                      <p data-testid="similar-match-count">
                        {t('transactions.matchesFound', { count: matched })}
                      </p>
                      {samples.length > 0 && (
                        <ul className="text-xs text-muted-foreground space-y-0.5 max-h-24 overflow-auto">
                          {samples.map((s) => (
                            <li key={s.id} className="truncate font-mono">
                              {s.description}
                            </li>
                          ))}
                        </ul>
                      )}
                    </>
                  )}
                </>
              )}
            </div>
          )}
        </div>

        <DialogFooter className="flex-col sm:flex-row gap-2">
          <Button type="button" variant="outline" onClick={onClose} disabled={creating} data-testid="pending-similar-dismiss">
            {wantRule ? t('common.cancel') : t('common.close')}
          </Button>
          {wantRule && !isStable && (
            <Button type="button" onClick={onOpenCustomRule} disabled={creating}>
              {t('transactions.createRule')}
            </Button>
          )}
          {wantRule && isStable && (
            <Button
              type="button"
              onClick={handleCreate}
              disabled={creating || previewQuery.isLoading || previewQuery.isError}
              data-testid="create-rule-and-apply"
            >
              {t('transactions.createRuleAndApply')}
            </Button>
          )}
        </DialogFooter>
      </DialogContent>
    </Dialog>
  )
}
