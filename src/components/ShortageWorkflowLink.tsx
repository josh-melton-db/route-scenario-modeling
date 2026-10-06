import { ArrowRight } from 'lucide-react'
import { Link } from 'react-router-dom'
import { buildShortageWorkflowHref } from '@/lib/networkLinks'
import { cn } from '@/lib/utils'

export default function ShortageWorkflowLink({
  scenarioId,
  runId,
  depotId,
  serviceDate,
  className,
}: {
  scenarioId: string
  runId?: string | null
  depotId?: string | null
  serviceDate?: string | null
  className?: string
}) {
  if (!depotId || !serviceDate) return null
  return (
    <Link
      to={buildShortageWorkflowHref({ scenarioId, runId, depotId, serviceDate })}
      className={cn(
        'inline-flex items-center gap-1.5 rounded-md border border-destructive/35 bg-destructive/5 px-2.5 py-1.5 text-xs font-medium text-destructive hover:bg-destructive/10',
        className,
      )}
    >
      Reallocate supply
      <ArrowRight className="h-3.5 w-3.5" />
    </Link>
  )
}
