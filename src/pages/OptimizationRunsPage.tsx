import { Link, useParams, useSearchParams } from 'react-router-dom'
import { ExternalLink, Loader2 } from 'lucide-react'
import ErrorState from '@/components/ErrorState'
import RunStatusBanner from '@/components/RunStatusBanner'
import { useRunStatus } from '@/api/queries'

const terminalStatuses = new Set(['succeeded', 'infeasible', 'failed'])

export default function OptimizationRunsPage() {
  const { runId } = useParams()
  const [searchParams] = useSearchParams()
  const scenarioId = searchParams.get('scenarioId')
  const run = useRunStatus(runId, scenarioId)

  if (run.error) return <ErrorState title="Could not load run" error={run.error} />

  return (
    <div className="flex flex-col gap-5 px-4 py-5 sm:px-6 lg:px-8">
      <header>
        <h1 className="text-2xl font-semibold tracking-tight">Optimization run</h1>
        <p className="mt-1 text-sm text-muted-foreground">
          Model Serving solver progress for the selected scenario.
        </p>
      </header>

      {run.isLoading || !run.data ? (
        <div className="flex h-96 items-center justify-center text-muted-foreground">
          <Loader2 className="mr-2 h-4 w-4 animate-spin" />
          Loading run...
        </div>
      ) : (
        <>
          <RunStatusBanner run={run.data} />
          <div className="flex flex-wrap justify-end gap-3">
            {run.data.databricks_run_url && (
              <a
                href={run.data.databricks_run_url}
                target="_blank"
                rel="noreferrer"
                className="inline-flex items-center gap-2 rounded-md border border-border px-4 py-2 text-sm font-semibold text-foreground"
              >
                Open serving endpoint
                <ExternalLink className="h-4 w-4" />
              </a>
            )}
            {terminalStatuses.has(run.data.status) && scenarioId && (
              <Link
                to={`/comparison/${scenarioId}`}
                className="rounded-md bg-primary px-4 py-2 text-sm font-semibold text-primary-foreground"
              >
                View comparison
              </Link>
            )}
          </div>
        </>
      )}
    </div>
  )
}
