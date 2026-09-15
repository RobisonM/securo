import { Link } from 'react-router-dom'
import { useTranslation } from 'react-i18next'
import { Upload } from 'lucide-react'
import { Button } from '@/components/ui/button'

export function DashboardEmptyState() {
  const { t } = useTranslation()
  return (
    <div className="bg-card rounded-xl border border-border shadow-sm px-6 py-12 text-center mb-5">
      <h2 className="text-lg font-semibold text-foreground mb-2">{t('dashboard.emptyTitle')}</h2>
      <p className="text-sm text-muted-foreground mb-5 max-w-md mx-auto">
        {t('dashboard.emptyDescription')}
      </p>
      <Button asChild className="gap-2">
        <Link to="/import">
          <Upload size={14} />
          {t('dashboard.emptyCta')}
        </Link>
      </Button>
    </div>
  )
}
