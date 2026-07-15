import { useEffect } from 'react'
import { Link, useNavigate, useParams, useSearchParams } from 'react-router-dom'
import { ExternalLink, Loader2 } from 'lucide-react'
import ConstraintPanel from '@/components/ConstraintPanel'
import ErrorState from '@/components/ErrorState'
import RunStatusBanner from '@/components/RunStatusBanner'
import { useRunStatus } from '@/api/queries'

const comparisonStatuses = new Set(['succeeded', 'infeasible'])

export default function OptimizationRunsPage() {
  const { runId } = useParams()
  const [searchParams] = useSearchParams()
  const scenarioId = searchParams.get('scenarioId')
  const navigate = useNavigate()
  const run = useRunStatus(runId, scenarioId)
  const precheckFailed =
    run.data?.validation?.valid === false ||
    run.data?.stages.some(
      (stage) => stage.stage_id === 'precheck' && stage.status === 'failed',
    ) === true

  useEffect(() => {
    if (
      !run.data ||
      precheckFailed ||
      !comparisonStatuses.has(run.data.status)
    ) {
      return
    }
    navigate(`/comparison/${run.data.scenario_id}`, { replace: true })
  }, [navigate, precheckFailed, run.data?.scenario_id, run.data?.status])

  if (run.error) return <ErrorState title="Could not load run" error={run.error} />

  const showRecovery = run.data?.status === 'failed' || precheckFailed

  return (
    <div className="flex flex-col gap-5 px-4 py-5 sm:px-6 lg:px-8">
      {run.isLoading || !run.data ? (
        <div className="flex h-96 items-center justify-center text-muted-foreground">
          <Loader2 className="mr-2 h-4 w-4 animate-spin" />
          Loading run...
        </div>
      ) : (
        <>
          <RunStatusBanner run={run.data} />
          {run.data.validation && !run.data.validation.valid && (
            <ConstraintPanel validation={run.data.validation} />
          )}
          {showRecovery && (
            <div className="flex flex-wrap items-center justify-between gap-3 rounded-lg border border-amber-500/40 bg-amber-500/10 p-4 text-sm">
              <div>
                <div className="font-semibold text-amber-100">
                  {precheckFailed
                    ? 'Precheck needs attention'
                    : 'Optimization did not complete'}
                </div>
                <p className="mt-1 text-amber-100/80">
                  Revise the scenario changes and launch a new run when ready.
                </p>
              </div>
              <Link
                to="/scenario"
                className="rounded-md border border-amber-300/40 px-3 py-2 text-sm font-semibold text-amber-50 hover:bg-amber-400/10"
              >
                Return to scenario builder
              </Link>
            </div>
          )}
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
          </div>
        </>
      )}
    </div>
  )
}
