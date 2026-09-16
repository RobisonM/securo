import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import { useTranslation } from 'react-i18next'
import type { ImportReviewTransaction, Category, CategoryGroup } from '@/types'
import { formatCurrency } from '@/lib/format'
import {
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from '@/components/ui/table'
import { Input } from '@/components/ui/input'
import { CategorySelect } from '@/components/category-select'
import { CategoryFilterDropdown } from '@/components/category-filter-dropdown'
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from '@/components/ui/select'

const ISO_DATE_RE = /^(\d{4})-(\d{2})-(\d{2})$/
const STORAGE_KEY_WIDTHS = 'securo.import.columns.widths'
const MIN_COL_WIDTH = 48
const MAX_COL_WIDTH = 800

type ImportColId =
  | 'toggle'
  | 'date'
  | 'description'
  | 'installment'
  | 'cardholder'
  | 'amount'
  | 'category'
  | 'status'

interface ImportColDef {
  id: ImportColId
  labelKey?: string
  defaultWidth: number
  align?: 'left' | 'right' | 'center'
  /** Checkbox column — no user-facing label, still resizable. */
  srOnly?: boolean
}

const IMPORT_COLUMNS: ImportColDef[] = [
  { id: 'toggle', defaultWidth: 44, srOnly: true },
  { id: 'date', labelKey: 'transactions.date', defaultWidth: 100 },
  { id: 'description', labelKey: 'transactions.description', defaultWidth: 280 },
  { id: 'installment', labelKey: 'transactions.colInstallment', defaultWidth: 80, align: 'center' },
  { id: 'cardholder', labelKey: 'transactions.colCardholder', defaultWidth: 130 },
  { id: 'amount', labelKey: 'transactions.amount', defaultWidth: 120, align: 'right' },
  { id: 'category', labelKey: 'import.category', defaultWidth: 180 },
  { id: 'status', labelKey: 'transactions.status', defaultWidth: 90 },
]

const COL_BY_ID = Object.fromEntries(IMPORT_COLUMNS.map((c) => [c.id, c])) as Record<
  ImportColId,
  ImportColDef
>

function loadWidths(): Partial<Record<ImportColId, number>> {
  try {
    const raw = localStorage.getItem(STORAGE_KEY_WIDTHS)
    if (!raw) return {}
    const parsed = JSON.parse(raw)
    if (!parsed || typeof parsed !== 'object') return {}
    const out: Partial<Record<ImportColId, number>> = {}
    for (const [k, v] of Object.entries(parsed)) {
      if (k in COL_BY_ID && typeof v === 'number' && v >= MIN_COL_WIDTH && v <= MAX_COL_WIDTH) {
        out[k as ImportColId] = v
      }
    }
    return out
  } catch {
    return {}
  }
}

function formatLocalDate(date: string, locale: string) {
  const match = ISO_DATE_RE.exec(date)
  if (!match) return new Date(date).toLocaleDateString(locale)
  return new Date(Number(match[1]), Number(match[2]) - 1, Number(match[3])).toLocaleDateString(locale)
}

interface ImportReviewTableProps {
  transactions: ImportReviewTransaction[]
  categories: Category[]
  groups: CategoryGroup[]
  userCurrency: string
  locale: string
  dateLocale: string
  searchQuery: string
  filterCategoryIds: string[]
  filterUncategorized: boolean
  statusFilter: 'all' | 'included' | 'excluded'
  currentPage: number
  onToggleExcluded: (id: string) => void
  onChangeCategory: (id: string, categoryId: string | null) => void
  onSearchChange: (query: string) => void
  onCategoryIdsChange: (ids: string[]) => void
  onUncategorizedChange: (value: boolean) => void
  onStatusFilterChange: (filter: 'all' | 'included' | 'excluded') => void
  onPageChange: (page: number) => void
}

export function ImportReviewTable({
  transactions,
  categories,
  groups,
  userCurrency,
  locale,
  dateLocale,
  searchQuery,
  filterCategoryIds,
  filterUncategorized,
  statusFilter,
  currentPage,
  onToggleExcluded,
  onChangeCategory,
  onSearchChange,
  onCategoryIdsChange,
  onUncategorizedChange,
  onStatusFilterChange,
  onPageChange,
}: ImportReviewTableProps) {
  const { t } = useTranslation()
  const [pageSize, setPageSize] = useState<number>(() => {
    try {
      const stored = localStorage.getItem('securo.import.pageSize')
      return stored ? Number(stored) : 50
    } catch {
      return 50
    }
  })
  const [widths, setWidths] = useState<Partial<Record<ImportColId, number>>>(() => loadWidths())
  const resizingRef = useRef<{ id: ImportColId; startX: number; startWidth: number } | null>(null)

  useEffect(() => {
    try {
      localStorage.setItem(STORAGE_KEY_WIDTHS, JSON.stringify(widths))
    } catch {
      /* quota / disabled */
    }
  }, [widths])

  const widthOf = useCallback(
    (id: ImportColId) => widths[id] ?? COL_BY_ID[id].defaultWidth,
    [widths],
  )

  const setWidth = useCallback((id: ImportColId, width: number) => {
    const clamped = Math.max(MIN_COL_WIDTH, Math.min(MAX_COL_WIDTH, Math.round(width)))
    setWidths((prev) => ({ ...prev, [id]: clamped }))
  }, [])

  const startResize = (e: React.PointerEvent<HTMLSpanElement>, id: ImportColId) => {
    e.preventDefault()
    e.stopPropagation()
    resizingRef.current = { id, startX: e.clientX, startWidth: widthOf(id) }
    const onMove = (ev: PointerEvent) => {
      const r = resizingRef.current
      if (!r) return
      setWidth(r.id, r.startWidth + (ev.clientX - r.startX))
    }
    const onUp = () => {
      resizingRef.current = null
      window.removeEventListener('pointermove', onMove)
      window.removeEventListener('pointerup', onUp)
    }
    window.addEventListener('pointermove', onMove)
    window.addEventListener('pointerup', onUp)
  }

  const tableWidth = useMemo(
    () => IMPORT_COLUMNS.reduce((sum, col) => sum + widthOf(col.id), 0),
    [widthOf],
  )

  const hasCategoryFilter = filterCategoryIds.length > 0 || filterUncategorized

  const filtered = useMemo(() => {
    return transactions.filter((tx) => {
      if (searchQuery) {
        const q = searchQuery.toLowerCase()
        if (!tx.description.toLowerCase().includes(q)) return false
      }
      if (hasCategoryFilter) {
        const catId =
          tx.selected_category_id !== undefined ? tx.selected_category_id : tx.suggested_category_id
        if (filterUncategorized && !filterCategoryIds.length) {
          if (catId) return false
        } else if (filterUncategorized) {
          if (catId && !filterCategoryIds.includes(catId)) return false
        } else {
          if (!catId || !filterCategoryIds.includes(catId)) return false
        }
      }
      if (statusFilter === 'included' && tx.excluded) return false
      if (statusFilter === 'excluded' && !tx.excluded) return false
      return true
    })
  }, [
    transactions,
    searchQuery,
    filterCategoryIds,
    filterUncategorized,
    hasCategoryFilter,
    statusFilter,
  ])

  const totalPages = Math.max(1, Math.ceil(filtered.length / pageSize))
  const safePage = Math.min(currentPage, totalPages)
  const pageItems = filtered.slice((safePage - 1) * pageSize, safePage * pageSize)

  const colStyle = (id: ImportColId) => {
    const w = widthOf(id)
    return { width: w, minWidth: w, maxWidth: w }
  }

  return (
    <div>
      {/* Filter bar */}
      <div className="px-5 py-3 border-b border-border bg-muted/30 flex flex-wrap items-center gap-3">
        <Input
          placeholder={t('import.searchTransactions')}
          value={searchQuery}
          onChange={(e) => {
            onSearchChange(e.target.value)
            onPageChange(1)
          }}
          className="max-w-xs h-8 text-sm border border-border rounded-md px-3 bg-card focus:outline-none focus-visible:ring-ring/30 focus-visible:ring-[2px]"
        />
        <CategoryFilterDropdown
          categoryIds={filterCategoryIds}
          onCategoryIdsChange={(ids) => {
            onCategoryIdsChange(ids)
            onPageChange(1)
          }}
          filterUncategorized={filterUncategorized}
          onUncategorizedChange={(v) => {
            onUncategorizedChange(v)
            onPageChange(1)
          }}
          categories={categories}
          groups={groups}
          label={t('import.filterCategory')}
        />
        <select
          className="border border-border rounded-md px-3 py-1.5 text-sm bg-card focus:outline-none focus-visible:ring-ring/30 focus-visible:ring-[2px]"
          value={statusFilter}
          onChange={(e) => {
            onStatusFilterChange(e.target.value as 'all' | 'included' | 'excluded')
            onPageChange(1)
          }}
        >
          <option value="all">{t('import.allStatus')}</option>
          <option value="included">{t('import.included')}</option>
          <option value="excluded">{t('import.excluded')}</option>
        </select>
      </div>

      {/* Single scrollport for both axes so the horizontal bar stays visible
          without scrolling to the bottom of a nested overflow-x wrapper. */}
      <div className="max-h-[min(60vh,560px)] overflow-auto">
        <table
          className="caption-bottom text-sm table-fixed"
          style={{ width: tableWidth, minWidth: tableWidth }}
        >
          <TableHeader className="sticky top-0 z-10 bg-card shadow-[inset_0_-1px_0_0_hsl(var(--border))]">
            <TableRow className="hover:bg-transparent bg-transparent border-b border-border">
              {IMPORT_COLUMNS.map((col) => {
                const align =
                  col.align === 'right'
                    ? 'text-right'
                    : col.align === 'center'
                      ? 'text-center'
                      : 'text-left'
                return (
                  <TableHead
                    key={col.id}
                    style={colStyle(col.id)}
                    className={`relative text-xs font-medium text-muted-foreground py-3 bg-card ${align} ${
                      col.id === 'toggle' ? 'pl-4' : ''
                    } ${col.id === 'status' ? 'pr-4' : ''}`}
                  >
                    {col.srOnly ? (
                      <span className="sr-only">Toggle</span>
                    ) : (
                      <span className="truncate block">{t(col.labelKey!)}</span>
                    )}
                    <span
                      onPointerDown={(e) => startResize(e, col.id)}
                      onClick={(e) => e.stopPropagation()}
                      aria-hidden="true"
                      className="absolute right-0 top-0 h-full w-2 -mr-1 cursor-col-resize select-none hover:bg-primary/40 active:bg-primary/60"
                    />
                  </TableHead>
                )
              })}
            </TableRow>
          </TableHeader>
          <TableBody>
            {pageItems.map((tx) => (
              <TableRow
                key={tx._id}
                className={`border-b border-border last:border-0 hover:bg-muted ${tx.excluded ? 'opacity-50' : ''}`}
              >
                <TableCell style={colStyle('toggle')} className="py-2.5 pl-4">
                  <input
                    type="checkbox"
                    checked={!tx.excluded}
                    onChange={() => onToggleExcluded(tx._id)}
                    className="rounded border-border text-primary focus:ring-primary"
                  />
                </TableCell>
                <TableCell
                  style={colStyle('date')}
                  className="py-2.5 text-xs text-muted-foreground whitespace-nowrap overflow-hidden text-ellipsis"
                >
                  {formatLocalDate(tx.date, dateLocale)}
                </TableCell>
                <TableCell
                  style={colStyle('description')}
                  className={`py-2.5 text-sm truncate ${tx.excluded ? 'line-through text-muted-foreground' : 'text-foreground'}`}
                  title={tx.description}
                >
                  {tx.description}
                </TableCell>
                <TableCell
                  style={colStyle('installment')}
                  className="py-2.5 text-xs text-muted-foreground text-center tabular-nums whitespace-nowrap overflow-hidden text-ellipsis"
                >
                  {tx.installment_number != null && tx.total_installments != null
                    ? `${tx.installment_number}/${tx.total_installments}`
                    : '—'}
                </TableCell>
                <TableCell
                  style={colStyle('cardholder')}
                  className="py-2.5 text-xs text-muted-foreground truncate"
                  title={tx.cardholder || undefined}
                >
                  {tx.cardholder || '—'}
                </TableCell>
                <TableCell
                  style={colStyle('amount')}
                  className={`py-2.5 text-right text-sm font-bold tabular-nums whitespace-nowrap overflow-hidden text-ellipsis ${
                    tx.type === 'credit' ? 'text-emerald-600' : 'text-rose-500'
                  }`}
                >
                  {tx.type === 'credit' ? '+' : '−'}
                  {formatCurrency(Math.abs(Number(tx.amount)), userCurrency, locale)}
                </TableCell>
                <TableCell style={colStyle('category')} className="py-2.5 overflow-hidden">
                  <CategorySelect
                    value={
                      tx.selected_category_id !== undefined
                        ? (tx.selected_category_id ?? '')
                        : (tx.suggested_category_id ?? '')
                    }
                    onChange={(v) => onChangeCategory(tx._id, v || null)}
                    categories={categories}
                    groups={groups}
                    placeholder={t('import.noCategory')}
                    allowNone
                    className="w-full border border-border rounded-md px-2 py-1 text-xs bg-card focus:outline-none focus-visible:ring-ring/30 focus-visible:ring-[2px]"
                  />
                </TableCell>
                <TableCell style={colStyle('status')} className="py-2.5 pr-4 whitespace-nowrap overflow-hidden">
                  {tx.excluded ? (
                    <span className="text-xs bg-muted text-muted-foreground px-2 py-0.5 rounded">
                      {t('import.excluded')}
                    </span>
                  ) : (
                    <span className="text-xs bg-emerald-50 text-emerald-700 px-2 py-0.5 rounded">
                      {t('import.included')}
                    </span>
                  )}
                </TableCell>
              </TableRow>
            ))}
          </TableBody>
        </table>
      </div>

      {/* Pagination */}
      {filtered.length > 10 && (
        <div className="px-5 py-3 border-t border-border flex flex-col sm:flex-row items-center justify-between gap-4 text-sm">
          {totalPages > 1 ? (
            <div className="flex items-center gap-4">
              <button
                className="text-muted-foreground hover:text-foreground disabled:opacity-30 font-medium"
                disabled={safePage <= 1}
                onClick={() => onPageChange(safePage - 1)}
              >
                ← {t('common.previous', 'Previous')}
              </button>
              <span className="text-xs text-muted-foreground">
                {t('import.page', { current: safePage, total: totalPages })}
              </span>
              <button
                className="text-muted-foreground hover:text-foreground disabled:opacity-30 font-medium"
                disabled={safePage >= totalPages}
                onClick={() => onPageChange(safePage + 1)}
              >
                {t('common.next', 'Next')} →
              </button>
            </div>
          ) : (
            <div className="hidden sm:block" />
          )}

          <div className="flex items-center gap-2">
            <span className="text-xs text-muted-foreground">
              {t('common.rowsPerPage', 'Rows per page')}
            </span>
            <Select
              value={String(pageSize)}
              onValueChange={(val) => {
                const nextSize = Number(val)
                setPageSize(nextSize)
                onPageChange(1)
                try {
                  localStorage.setItem('securo.import.pageSize', String(nextSize))
                } catch {
                  // ignored
                }
              }}
            >
              <SelectTrigger className="w-[70px] h-8 text-xs">
                <SelectValue placeholder={pageSize} />
              </SelectTrigger>
              <SelectContent>
                <SelectItem value="10">10</SelectItem>
                <SelectItem value="20">20</SelectItem>
                <SelectItem value="50">50</SelectItem>
                <SelectItem value="100">100</SelectItem>
              </SelectContent>
            </Select>
          </div>
        </div>
      )}
    </div>
  )
}
