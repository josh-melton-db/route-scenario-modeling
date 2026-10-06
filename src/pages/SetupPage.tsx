import { AlertCircle, CheckCircle2, Loader2, RefreshCw } from 'lucide-react'
import { useMutation, useQueryClient } from '@tanstack/react-query'
import { queryKeys, useReadiness } from '@/api/queries'
import { api } from '@/api/client'
import type { ReadinessCheck, ReadinessSnapshot } from '@/api/types'

const labels: Record<string, string> = {
  lakebase: 'Lakebase state',
  sql_warehouse: 'SQL warehouse',
  route_solver: 'Route solver',
  durable_workers: 'Background workers',
  routing_coverage: 'Routing coverage',
}

function detail(check: ReadinessCheck): string {
  if (check.message) return check.message
  if (check.skipped) return `Not required for the ${check.backend ?? 'current'} data backend.`
  if (check.mode) {
    const warmup = check.warmup
    const status = warmup?.configured
      ? warmup.state === 'ready' ? 'Solver warm-up completed.'
        : warmup.state === 'warming' ? 'Solver is warming up.'
          : warmup.state === 'failed' ? `Solver warm-up failed: ${warmup.error ?? 'Check endpoint status.'}`
            : 'Click Ping to warm the solver before presenting.'
      : ''
    return `Mode: ${check.mode}. ${status}`
  }
  if (check.migration) return `Migration ${check.migration.version}: ${check.migration.state}`
  if (check.deployment_class === 'accelerator') return check.production_recommendation ?? 'Accelerator worker pool.'
  return check.ready ? 'Configured and available.' : 'Configuration is incomplete.'
}

function ComputePing({ name, check }: { name: 'sql_warehouse' | 'route_solver'; check: ReadinessCheck }) {
  const queryClient = useQueryClient()
  const ping = useMutation({
    mutationFn: () => api.pingCompute(name === 'sql_warehouse' ? 'sql-warehouse' : 'route-solver'),
    onSuccess: (warmup) => {
      queryClient.setQueryData<ReadinessSnapshot>(queryKeys.readiness, (current) => current
        ? { ...current, checks: { ...current.checks, [name]: { ...current.checks[name], warmup } } }
        : current)
      void queryClient.invalidateQueries({ queryKey: queryKeys.readiness })
    },
  })
  const warming = ping.isPending || check.warmup?.state === 'warming'
  const status = check.warmup
  return <div className="mt-3 space-y-2 border-t border-border pt-3">
    <button type="button" aria-label={`Ping ${labels[name]}`} onClick={() => ping.mutate()}
      disabled={!check.ping_available || warming}
      className="inline-flex items-center gap-2 rounded-md border border-border px-3 py-1.5 text-sm hover:bg-accent disabled:opacity-50">
      {warming && <Loader2 className="h-4 w-4 animate-spin" />}
      {warming ? 'Pinging…' : 'Ping'}
    </button>
    <p className="text-xs text-muted-foreground" role="status">
      {!check.ping_available ? 'Remote compute is not configured for this environment.'
        : warming ? 'Waking up. This can take a few minutes.'
          : status?.state === 'ready' ? `Last ping succeeded${status.completed_at ? ` at ${new Date(status.completed_at).toLocaleTimeString()}` : ''}.`
            : status?.state === 'skipped' ? 'Ping skipped: this resource is not configured.'
              : 'Send a small request to wake this resource before your demo.'}
    </p>
    {(ping.error || status?.state === 'failed') && <p role="alert" className="text-xs text-destructive">
      Ping failed: {ping.error ? String(ping.error) : status?.error ?? 'Try again or check resource access.'}
    </p>}
  </div>
}

export default function SetupPage() {
  const readiness = useReadiness()
  const checks = Object.entries(readiness.data?.checks ?? {})

  return (
    <section className="mx-auto w-full max-w-5xl space-y-6 p-6 lg:p-10">
      <div className="flex items-start justify-between gap-4">
        <div>
          <p className="text-xs font-semibold uppercase tracking-[0.18em] text-primary">Environment</p>
          <h1 className="mt-2 text-3xl font-semibold">Setup and readiness</h1>
          <p className="mt-2 max-w-2xl text-sm text-muted-foreground">
            Check the application dependencies before a workshop or deployment.
          </p>
        </div>
        <button
          type="button"
          onClick={() => void readiness.refetch()}
          disabled={readiness.isFetching}
          className="flex items-center gap-2 rounded-md border border-border bg-card px-3 py-2 text-sm hover:bg-accent disabled:opacity-50"
        >
          {readiness.isFetching ? <Loader2 className="h-4 w-4 animate-spin" /> : <RefreshCw className="h-4 w-4" />}
          Refresh
        </button>
      </div>

      {readiness.isError ? (
        <div className="rounded-lg border border-destructive/50 bg-destructive/10 p-4 text-sm">
          The readiness endpoint could not be reached. Confirm the backend is running.
        </div>
      ) : (
        <>
          <div className="rounded-lg border border-border bg-card p-5">
            <div className="flex items-center gap-3">
              {readiness.data?.status === 'ready' ? (
                <CheckCircle2 className="h-6 w-6 text-emerald-400" />
              ) : (
                <AlertCircle className="h-6 w-6 text-amber-400" />
              )}
              <div>
                <h2 className="font-semibold">{readiness.data?.status === 'ready' ? 'Ready to use' : 'Setup needs attention'}</h2>
                <p className="text-sm text-muted-foreground">Status refreshes every 15 seconds, and more often while a resource wakes up.</p>
              </div>
            </div>
          </div>

          <div className="grid gap-3 md:grid-cols-2">
            {checks.map(([name, check]) => (
              <article key={name} className="rounded-lg border border-border bg-card p-4">
                <div className="flex items-center gap-2">
                  {check.ready ? <CheckCircle2 className="h-5 w-5 text-emerald-400" /> : <AlertCircle className="h-5 w-5 text-amber-400" />}
                  <h2 className="font-medium">{labels[name] ?? name.replaceAll('_', ' ')}</h2>
                </div>
                <p className="mt-2 text-sm text-muted-foreground">{detail(check)}</p>
                {(name === 'sql_warehouse' || name === 'route_solver') && <ComputePing name={name} check={check} />}
              </article>
            ))}
          </div>
        </>
      )}
    </section>
  )
}
