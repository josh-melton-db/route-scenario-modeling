import { useEffect, useMemo, useRef, useState } from 'react'
import { Navigate, useNavigate, useParams, useSearchParams } from 'react-router-dom'
import {
  AlertTriangle,
  ArrowRight,
  Ban,
  Loader2,
  Play,
  Save,
  Search,
  ShieldCheck,
  Trash2,
} from 'lucide-react'
import EmptyState from '@/components/EmptyState'
import ErrorState from '@/components/ErrorState'
import KpiCard from '@/components/KpiCard'
import NetworkDetailDrawer from '@/components/NetworkDetailDrawer'
import NetworkFlowMap from '@/components/NetworkFlowMap'
import NetworkTariffChangeCard from '@/components/NetworkTariffChangeCard'
import NetworkBaselineActions from '@/components/NetworkBaselineActions'
import {
  useDeleteNetworkScenario,
  useNetworkOptions,
  useNetworkOverview,
  useNetworkScenario,
  useNetworkScenarioResult,
  useRunNetworkScenario,
  useUpdateNetworkScenario,
  useValidateNetworkScenario,
} from '@/api/queries'
import type {
  NetworkFlowChargeDetail,
  NetworkScenario,
  NetworkScenarioAssumptions,
  NetworkScenarioException,
} from '@/api/types'
import { formatCurrency, formatNumber, formatPercent } from '@/lib/format'
import {
  buildDepotAnalysisHref,
  buildNetworkScenarioReturnHref,
  buildRouteWorkspaceHref,
} from '@/lib/networkLinks'
import { cn } from '@/lib/utils'

const SOLVED_STATUSES = new Set(['solved', 'depot_plans_running', 'reconciliation_required', 'reconciled', 'published'])

type NetworkDraft = {
  scenarioId: string
  name: string
  assumptions: NetworkScenarioAssumptions
  dirty: boolean
}

export default function NetworkScenarioDetailPage() {
  const { scenarioId = '', tab = 'scenario' } = useParams()
  const [searchParams] = useSearchParams()
  const pinnedRunId = searchParams.get('run')
  const navigate = useNavigate()
  const options = useNetworkOptions()
  const scenario = useNetworkScenario(scenarioId)
  const hasResult = SOLVED_STATUSES.has(scenario.data?.status ?? 'draft')
  const result = useNetworkScenarioResult(
    scenarioId,
    hasResult || Boolean(pinnedRunId),
    pinnedRunId,
  )
  const updateScenario = useUpdateNetworkScenario(scenarioId)
  const validateScenario = useValidateNetworkScenario(scenarioId)
  const runScenario = useRunNetworkScenario(scenarioId)
  const deleteScenario = useDeleteNetworkScenario()
  const basePath = `/network/scenarios/${encodeURIComponent(scenarioId)}`
  const [actionError, setActionError] = useState<string | null>(null)
  const [draft, setDraft] = useState<NetworkDraft | null>(null)

  const context = scenario.data
    ? {
        demand_plan_version_id: scenario.data.demand_plan_version_id,
        capacity_plan_version_id: scenario.data.capacity_plan_version_id,
        horizon_start: scenario.data.horizon_start,
        horizon_end: scenario.data.horizon_end,
        region_id: scenario.data.region_id,
        lane_type: 'LINEHAUL' as const,
        metric: 'assigned_flow' as const,
      }
    : null
  const linehaulOverview = useNetworkOverview(context)

  if (!['scenario', 'flow', 'lanes', 'charges', 'exceptions'].includes(tab)) {
    return <Navigate to={`${basePath}/scenario`} replace />
  }
  if (scenario.error) {
    return <ErrorState title="Could not load network scenario" error={scenario.error} />
  }
  if (options.error) {
    return <ErrorState title="Could not load network options" error={options.error} />
  }
  if (scenario.isLoading || !scenario.data || !options.data) {
    return (
      <div className="flex h-96 items-center justify-center text-muted-foreground">
        <Loader2 className="mr-2 h-4 w-4 animate-spin" /> Loading scenario...
      </div>
    )
  }

  const busy =
    updateScenario.isPending || validateScenario.isPending || runScenario.isPending

  const hasPendingDraft = draft?.scenarioId === scenarioId && draft.dirty
  const planApplied = hasResult && !hasPendingDraft

  async function save(next: {
    scenario_name?: string
    assumptions?: NetworkScenarioAssumptions
  }): Promise<boolean> {
    setActionError(null)
    try {
      await updateScenario.mutateAsync(next)
      return true
    } catch (err) {
      setActionError(String(err))
      return false
    }
  }

  async function validate() {
    setActionError(null)
    try {
      await validateScenario.mutateAsync()
    } catch (err) {
      setActionError(String(err))
    }
  }

  async function run() {
    setActionError(null)
    try {
      const pendingDraft = draft?.scenarioId === scenarioId && draft.dirty ? draft : null
      if (pendingDraft) {
        await updateScenario.mutateAsync({
          scenario_name: pendingDraft.name.trim() || scenario.data?.scenario_name,
          assumptions: pendingDraft.assumptions,
        })
        setDraft(null)
      }
      if (pendingDraft || !scenario.data?.validation?.valid) {
        const validated = await validateScenario.mutateAsync()
        if (!validated.validation?.valid) {
          navigate(`${basePath}/scenario`)
          return
        }
      }
      const completed = await runScenario.mutateAsync()
      const runId = completed.result.run_id
      navigate(runId ? `${basePath}/flow?run=${encodeURIComponent(runId)}` : `${basePath}/flow`)
    } catch (err) {
      setActionError(String(err))
    }
  }

  async function handleDelete() {
    setActionError(null)
    if (!window.confirm(`Delete "${scenario.data?.scenario_name ?? 'this scenario'}"? This cannot be undone.`)) {
      return
    }
    try {
      await deleteScenario.mutateAsync(scenarioId)
      navigate('/network')
    } catch (err) {
      setActionError(String(err))
    }
  }

  return (
    <div className="flex flex-col gap-5 px-4 py-5 sm:px-6 lg:px-8">
      {tab === 'scenario' && (
      <header>
        <div className="flex flex-wrap items-start justify-between gap-4">
          <div>
            <div className="flex flex-wrap items-center gap-2">
              <h1 className="text-2xl font-semibold tracking-tight">
                {scenario.data.scenario_name}
              </h1>
              <StatusPill scenario={scenario.data} />
            </div>
            <p className="mt-1 text-sm text-muted-foreground">
              {regionName(options.data.regions, scenario.data.region_id)} ·{' '}
              {scenario.data.horizon_start} → {scenario.data.horizon_end} · Revision{' '}
              {scenario.data.revision}
            </p>
          </div>
          <div className="flex flex-wrap gap-2">
            {planApplied ? (
              <button
                type="button"
                onClick={() => navigate(`${basePath}/flow`)}
                className="inline-flex h-10 items-center gap-2 rounded-md bg-primary px-4 text-sm font-semibold text-primary-foreground"
              >
                <ArrowRight className="h-4 w-4" />
                View this plan
              </button>
            ) : (
              <button
                type="button"
                onClick={() => void run()}
                disabled={busy || scenario.data.status === 'published'}
                className="inline-flex h-10 items-center gap-2 rounded-md bg-primary px-4 text-sm font-semibold text-primary-foreground disabled:cursor-not-allowed disabled:opacity-50"
              >
                {runScenario.isPending ? (
                  <Loader2 className="h-4 w-4 animate-spin" />
                ) : (
                  <Play className="h-4 w-4" />
                )}
                Run fixed-capacity plan
              </button>
            )}
          </div>
        </div>
      </header>
      )}

      {actionError && (
        <div className="rounded-md border border-destructive/40 bg-destructive/10 p-3 text-sm text-destructive">
          {actionError}
        </div>
      )}

      {tab === 'scenario' && (
        <ScenarioTab
          scenario={scenario.data}
          draft={draft?.scenarioId === scenarioId && draft.dirty ? draft : null}
          onDraftChange={setDraft}
          facilities={options.data.facilities}
          regions={options.data.regions}
          lanes={linehaulOverview.data?.lanes ?? []}
          busy={busy}
          onSave={save}
          onValidate={validate}
          onDelete={handleDelete}
          deletePending={deleteScenario.isPending}
        />
      )}
      {tab === 'flow' && (
        <FlowTab
          result={result}
          scenario={scenario.data}
          onBackToScenario={() => navigate(`${basePath}/scenario`)}
        />
      )}
      {tab === 'lanes' && (
        <LaneChangesTab
          result={result}
          onBackToScenario={() => navigate(`${basePath}/scenario`)}
        />
      )}
      {tab === 'charges' && (
        <RateAuditTab result={result} onBackToScenario={() => navigate(`${basePath}/scenario`)} />
      )}
      {tab === 'exceptions' && (
        <ExceptionsTab
          result={result}
          facilities={options.data.facilities}
          onBackToScenario={() => navigate(`${basePath}/scenario`)}
        />
      )}
    </div>
  )
}

function StatusPill({ scenario }: { scenario: NetworkScenario }) {
  const failed = scenario.status === 'infeasible' || scenario.status === 'failed'
  const ready = scenario.status === 'validated'
  const solved = SOLVED_STATUSES.has(scenario.status)
  return (
    <span
      className={cn(
        'rounded-full px-2 py-0.5 text-[11px] font-medium capitalize',
        failed
          ? 'bg-destructive/10 text-destructive'
          : ready
            ? 'bg-emerald-500/10 text-emerald-600 dark:text-emerald-400'
            : solved
              ? 'bg-primary/15 text-primary'
              : 'bg-muted text-muted-foreground',
      )}
    >
      {scenario.status.replace(/_/g, ' ')}
    </span>
  )
}

function RegionToggle({
  regionName,
  facilityIds,
  disabledIds,
  onToggle,
}: {
  regionName: string
  facilityIds: string[]
  disabledIds: Set<string>
  onToggle: (disable: boolean) => void
}) {
  const ref = useRef<HTMLInputElement>(null)
  const disabledCount = facilityIds.filter((id) => disabledIds.has(id)).length
  const allDisabled = facilityIds.length > 0 && disabledCount === facilityIds.length
  const partiallyDisabled = disabledCount > 0 && !allDisabled

  useEffect(() => {
    if (ref.current) ref.current.indeterminate = partiallyDisabled
  }, [partiallyDisabled])

  return (
    <label className="flex cursor-pointer items-center gap-2 border-b border-border/60 bg-muted/40 px-3 py-1.5 text-[11px] font-semibold uppercase tracking-wide text-muted-foreground">
      <input
        ref={ref}
        type="checkbox"
        checked={allDisabled}
        aria-label={`Disable every facility in ${regionName}`}
        onChange={() => onToggle(!allDisabled)}
        className="h-3.5 w-3.5"
      />
      <span className="flex-1">{regionName}</span>
      <span className="font-normal normal-case tracking-normal">
        {disabledCount}/{facilityIds.length}
      </span>
    </label>
  )
}

function regionName(regions: { region_id: string; region_name: string }[], regionId: string) {
  if (regionId === 'ALL') return 'All regions'
  return regions.find((row) => row.region_id === regionId)?.region_name ?? regionId
}

/* ------------------------------ Scenario tab ------------------------------ */

function ScenarioTab({
  scenario,
  draft,
  onDraftChange,
  facilities,
  regions,
  lanes,
  busy,
  onSave,
  onValidate,
  onDelete,
  deletePending,
}: {
  scenario: NetworkScenario
  draft: NetworkDraft | null
  onDraftChange: (draft: NetworkDraft | null) => void
  facilities: { facility_id: string; facility_name: string; facility_type: string; region_id: string }[]
  regions: { region_id: string; region_name: string }[]
  lanes: { lane_id: string; lane_name: string }[]
  busy: boolean
  onSave: (next: { scenario_name?: string; assumptions?: NetworkScenarioAssumptions }) => Promise<boolean>
  onValidate: () => Promise<void>
  onDelete: () => Promise<void>
  deletePending: boolean
}) {
  const name = draft?.name ?? scenario.scenario_name
  const assumptions = draft?.assumptions ?? scenario.assumptions
  const dirty = draft?.dirty ?? false

  const disabledIds = new Set(assumptions.disabled_facility_ids)
  const disabledLaneIds = new Set(assumptions.disabled_lane_ids)
  const adjustedLaneIds = new Set(Object.keys(assumptions.lane_cost_adjustments_pct))
  const changedLaneIds = new Set([...disabledLaneIds, ...adjustedLaneIds])
  const [addLaneId, setAddLaneId] = useState('')
  const [addLaneMode, setAddLaneMode] = useState<'disable' | 'adjust'>('disable')
  const [addAdjustPct, setAddAdjustPct] = useState('10')

  function touchAssumptions(next: NetworkScenarioAssumptions) {
    onDraftChange({ scenarioId: scenario.scenario_id, name, assumptions: next, dirty: true })
  }

  function toggleFacility(facilityId: string) {
    toggleFacilities([facilityId], !disabledIds.has(facilityId))
  }

  function toggleFacilities(facilityIds: string[], disable: boolean) {
    const next = new Set(assumptions.disabled_facility_ids)
    for (const facilityId of facilityIds) {
      if (disable) next.add(facilityId)
      else next.delete(facilityId)
    }
    touchAssumptions({ ...assumptions, disabled_facility_ids: [...next].sort() })
  }

  function addLaneOverride() {
    const laneId = addLaneId
    if (!laneId) return
    if (addLaneMode === 'disable') {
      const next = new Set(assumptions.disabled_lane_ids)
      next.add(laneId)
      touchAssumptions({
        ...assumptions,
        disabled_lane_ids: [...next].sort(),
        lane_cost_adjustments_pct: Object.fromEntries(
          Object.entries(assumptions.lane_cost_adjustments_pct).filter(
            ([key]) => key !== laneId,
          ),
        ),
      })
    } else {
      const pct = Number(addAdjustPct)
      if (!Number.isFinite(pct)) return
      touchAssumptions({
        ...assumptions,
        disabled_lane_ids: assumptions.disabled_lane_ids.filter((id) => id !== laneId),
        lane_cost_adjustments_pct: {
          ...assumptions.lane_cost_adjustments_pct,
          [laneId]: pct,
        },
      })
    }
    setAddLaneId('')
  }

  const validation = scenario.validation
  const canRun = validation?.valid && !dirty

  return (
    <div className="flex flex-col gap-4">
      <section className="rounded-lg border border-border bg-card p-4">
        <h2 className="text-sm font-semibold">Starting plan</h2>
        <p className="mt-1 text-xs text-muted-foreground">
          Published baseline · demand {scenario.demand_plan_version_id} · capacity {scenario.capacity_plan_version_id} · {scenario.horizon_start} to {scenario.horizon_end}
        </p>
      </section>
      <NetworkTariffChangeCard
        rules={assumptions.tariffs ?? []}
        horizonStart={scenario.horizon_start}
        horizonEnd={scenario.horizon_end}
        onChange={(tariffs) => touchAssumptions({ ...assumptions, tariffs })}
      />
      <div className="grid gap-4 lg:grid-cols-[2fr_1fr]">
        <section className="flex flex-col gap-4 rounded-lg border border-border bg-card p-4">
          <div>
            <h2 className="text-sm font-semibold">Scenario settings and network changes</h2>
            <p className="mt-1 text-xs text-muted-foreground">
              Facility and lane cards are combined with tariff rules when the plan runs.
            </p>
          </div>
          <label className="flex flex-col gap-1.5 text-sm">
            <span className="font-medium">Scenario name</span>
            <input
              value={name}
              onChange={(event) => {
                onDraftChange({
                  scenarioId: scenario.scenario_id,
                  name: event.target.value,
                  assumptions,
                  dirty: true,
                })
              }}
              className="h-10 rounded-md border border-border bg-background px-3 text-sm"
            />
          </label>

          <label className="flex flex-col gap-1.5 text-sm">
            <span className="font-medium">Unmet-demand penalty ($ / case)</span>
            <input
              type="number"
              min={0}
              value={assumptions.unmet_penalty_per_case}
              onChange={(event) =>
                touchAssumptions({
                  ...assumptions,
                  unmet_penalty_per_case: Number(event.target.value) || 0,
                })
              }
              className="h-10 w-40 rounded-md border border-border bg-background px-3 text-sm"
            />
            <span className="text-xs text-muted-foreground">
              Drives how strongly the solver prefers serving demand over cost.
              Capacity is never invented either way.
            </span>
          </label>

          <div className="flex flex-col gap-2 rounded-md border border-border/70 p-3">
            <span className="text-sm font-semibold">Change facility availability</span>
            <span className="text-xs text-muted-foreground">Disable DCs or depots while retaining published capacity for comparison.</span>
            <div className="max-h-64 overflow-auto rounded-md border border-border">
              {regions
                .filter((region) => region.region_id !== 'ALL')
                .map((region) => {
                  const regionFacilities = facilities.filter(
                    (row) => row.region_id === region.region_id,
                  )
                  return (
                  <div key={region.region_id}>
                    <RegionToggle
                      regionName={region.region_name}
                      facilityIds={regionFacilities.map((row) => row.facility_id)}
                      disabledIds={disabledIds}
                      onToggle={(disable) =>
                        toggleFacilities(
                          regionFacilities.map((row) => row.facility_id),
                          disable,
                        )
                      }
                    />
                    {regionFacilities
                      .map((facility) => (
                        <label
                          key={facility.facility_id}
                          className="flex cursor-pointer items-center gap-2 border-b border-border/40 px-3 py-1.5 text-sm last:border-0"
                        >
                          <input
                            type="checkbox"
                            checked={disabledIds.has(facility.facility_id)}
                            onChange={() => toggleFacility(facility.facility_id)}
                            className="h-4 w-4"
                          />
                          <span className="flex-1">{facility.facility_name}</span>
                          <span className="text-[10px] uppercase tracking-wide text-muted-foreground">
                            {facility.facility_type === 'distribution_center' ? 'DC' : 'Depot'}
                          </span>
                        </label>
                      ))}
                  </div>
                  )
                })}
            </div>
          </div>

          <div className="flex flex-col gap-2 rounded-md border border-border/70 p-3">
            <span className="text-sm font-semibold">Restrict or price a lane</span>
            <span className="text-xs text-muted-foreground">Disable a linehaul lane or adjust its planning cost assumption.</span>
            <div className="flex flex-wrap items-center gap-2">
              <select
                value={addLaneId}
                onChange={(event) => setAddLaneId(event.target.value)}
                className="h-9 min-w-56 flex-1 rounded-md border border-border bg-background px-2 text-sm"
              >
                <option value="">Select a linehaul lane…</option>
                {lanes
                  .filter((lane) => !changedLaneIds.has(lane.lane_id))
                  .map((lane) => (
                    <option key={lane.lane_id} value={lane.lane_id}>
                      {lane.lane_name}
                    </option>
                  ))}
              </select>
              <select
                value={addLaneMode}
                onChange={(event) =>
                  setAddLaneMode(event.target.value as 'disable' | 'adjust')
                }
                className="h-9 rounded-md border border-border bg-background px-2 text-sm"
              >
                <option value="disable">Disable lane</option>
                <option value="adjust">Adjust cost</option>
              </select>
              {addLaneMode === 'adjust' && (
                <input
                  type="number"
                  value={addAdjustPct}
                  onChange={(event) => setAddAdjustPct(event.target.value)}
                  className="h-9 w-20 rounded-md border border-border bg-background px-2 text-sm"
                  aria-label="Cost adjustment percent"
                />
              )}
              <button
                type="button"
                onClick={addLaneOverride}
                disabled={!addLaneId}
                className="h-9 rounded-md border border-border bg-background px-3 text-sm font-medium hover:bg-accent/50 disabled:opacity-50"
              >
                Add
              </button>
            </div>
            {changedLaneIds.size > 0 ? (
              <ul className="divide-y divide-border/60 rounded-md border border-border text-sm">
                {assumptions.disabled_lane_ids.map((laneId) => (
                  <OverrideRow
                    key={laneId}
                    laneName={laneNameFor(lanes, laneId)}
                    detail="Disabled"
                    onRemove={() =>
                      touchAssumptions({
                        ...assumptions,
                        disabled_lane_ids: assumptions.disabled_lane_ids.filter(
                          (id) => id !== laneId,
                        ),
                      })
                    }
                  />
                ))}
                {Object.entries(assumptions.lane_cost_adjustments_pct).map(
                  ([laneId, pct]) => (
                    <OverrideRow
                      key={laneId}
                      laneName={laneNameFor(lanes, laneId)}
                      detail={`Cost ${pct > 0 ? '+' : ''}${pct}%`}
                      onRemove={() => {
                        const next = { ...assumptions.lane_cost_adjustments_pct }
                        delete next[laneId]
                        touchAssumptions({
                          ...assumptions,
                          lane_cost_adjustments_pct: next,
                        })
                      }}
                    />
                  ),
                )}
              </ul>
            ) : (
              <p className="text-xs text-muted-foreground">
                No lane overrides. The solver may use any permitted linehaul lane at
                published capacity.
              </p>
            )}
          </div>
        </section>

        <section className="flex flex-col gap-3 rounded-lg border border-border bg-card p-4">
          <h2 className="text-sm font-semibold">Validate and run</h2>
          <div className="flex flex-wrap gap-2">
            <button
              type="button"
              onClick={() => {
                void onSave({
                  scenario_name: name.trim() || scenario.scenario_name,
                  assumptions,
                }).then((saved) => {
                  if (saved) onDraftChange(null)
                })
              }}
              disabled={!dirty || busy}
              className="inline-flex h-9 items-center gap-2 rounded-md border border-border bg-background px-3 text-sm font-medium hover:bg-accent/50 disabled:cursor-not-allowed disabled:opacity-50"
            >
              <Save className="h-4 w-4" />
              Save changes
            </button>
            <button
              type="button"
              onClick={() => void onValidate()}
              disabled={dirty || busy}
              className="inline-flex h-9 items-center gap-2 rounded-md border border-border bg-background px-3 text-sm font-medium hover:bg-accent/50 disabled:cursor-not-allowed disabled:opacity-50"
            >
              <ShieldCheck className="h-4 w-4" />
              Validate
            </button>
          </div>
          {dirty && (
            <p className="text-xs text-amber-500">
              Unsaved changes — save and validate before running the plan.
            </p>
          )}
          {validation ? (
            <div className="flex flex-col gap-2">
              <p
                className={cn(
                  'text-sm font-medium',
                  validation.valid ? 'text-emerald-600 dark:text-emerald-400' : 'text-destructive',
                )}
              >
                {validation.summary}
              </p>
              <ul className="flex flex-col gap-1.5">
                {validation.issues.map((issue, index) => (
                  <li
                    key={`${issue.code}-${issue.entity_id ?? index}`}
                    className={cn(
                      'rounded-md border px-2.5 py-1.5 text-xs',
                      issue.severity === 'error'
                        ? 'border-destructive/40 bg-destructive/10 text-destructive'
                        : issue.severity === 'warning'
                          ? 'border-amber-500/40 bg-amber-500/5 text-amber-600 dark:text-amber-400'
                          : 'border-border bg-muted/40 text-muted-foreground',
                    )}
                  >
                    {issue.message}
                  </li>
                ))}
              </ul>
            </div>
          ) : (
            <p className="text-xs text-muted-foreground">
              Validation checks assumptions against the published plans before the
              solver runs.
            </p>
          )}
          <p className="text-xs text-muted-foreground">
            {canRun
              ? 'Ready to run from the header button.'
              : 'Save, then validate, to enable Run.'}
          </p>
          <button
            type="button"
            onClick={() => void onDelete()}
            disabled={busy || deletePending || scenario.status === 'published'}
            className="mt-auto inline-flex h-9 items-center gap-2 self-start rounded-md border border-destructive/50 px-3 text-sm font-medium text-destructive hover:bg-destructive/10 disabled:cursor-not-allowed disabled:opacity-50"
          >
            <Trash2 className="h-4 w-4" />
            Delete scenario
          </button>
        </section>
      </div>
    </div>
  )
}

function laneNameFor(lanes: { lane_id: string; lane_name: string }[], laneId: string) {
  return lanes.find((lane) => lane.lane_id === laneId)?.lane_name ?? laneId
}

function OverrideRow({
  laneName,
  detail,
  onRemove,
}: {
  laneName: string
  detail: string
  onRemove: () => void
}) {
  return (
    <li className="flex items-center gap-2 px-3 py-2">
      <span className="min-w-0 flex-1 truncate">{laneName}</span>
      <span className="shrink-0 text-xs text-muted-foreground">{detail}</span>
      <button
        type="button"
        onClick={onRemove}
        className="shrink-0 rounded-md px-1.5 py-0.5 text-xs text-destructive hover:bg-destructive/10"
      >
        Remove
      </button>
    </li>
  )
}

/* -------------------------------- Flow tab -------------------------------- */

type ResultQuery = ReturnType<typeof useNetworkScenarioResult>

function FlowTab({
  result,
  scenario,
  onBackToScenario,
}: {
  result: ResultQuery
  scenario: NetworkScenario
  onBackToScenario: () => void
}) {
  const navigate = useNavigate()
  const [searchParams] = useSearchParams()
  const pinnedRunId = searchParams.get('run') ?? result.data?.run_id
  const networkReturn = buildNetworkScenarioReturnHref(scenario.scenario_id, pinnedRunId)
  const [selectedFacilityId, setSelectedFacilityId] = useState<string | null>(null)
  const [selectedLaneId, setSelectedLaneId] = useState<string | null>(null)

  // Scenario shortfalls come from the run's exceptions; the network drawer falls
  // back to demand minus assigned when no scenario context is passed in.
  const unmetByFacility: Record<string, number> = {}
  for (const exception of result.data?.exceptions ?? []) {
    if (exception.exception_type !== 'unmet_demand' || !exception.entity_id) continue
    unmetByFacility[exception.entity_id] =
      (unmetByFacility[exception.entity_id] ?? 0) + (exception.unmet_units ?? 0)
  }

  if (result.isLoading) {
    return (
      <div className="flex h-72 items-center justify-center text-muted-foreground">
        <Loader2 className="mr-2 h-4 w-4 animate-spin" /> Loading plan results...
      </div>
    )
  }
  if (result.error || !result.data) {
    return (
      <EmptyState
        title="No plan results yet"
        description="Run the fixed-capacity plan from the Scenario tab to generate flow, rates, and exceptions."
        action={{ label: 'Go to Scenario tab', onClick: onBackToScenario }}
      />
    )
  }

  const { overview, baseline_overview, kpi_deltas: deltas } = result.data
  const tariffTotal = result.data.tariff_total_cost
  const baselineTariffExposure = result.data.baseline_tariff_exposure
  const tariffDifference = baselineTariffExposure != null && tariffTotal != null
    ? baselineTariffExposure - tariffTotal
    : null
  const crossBorderCases = result.data.cross_border_assigned_units
  const domesticShift = result.data.domestic_shift_units
  const facilities = overview.facilities
  const selectedFacility =
    facilities.find((row) => row.facility_id === selectedFacilityId) ?? null
  const selectedLane =
    overview.lanes.find((row) => row.lane_id === selectedLaneId) ?? null
  const openFacility = (facilityId: string | null) => {
    if (!facilityId) {
      setSelectedFacilityId(null)
      return
    }
    const facility = facilities.find((row) => row.facility_id === facilityId)
    if (!facility) return

    if (facility.facility_type === 'distribution_center') {
      setSelectedFacilityId(facilityId)
      setSelectedLaneId(null)
      return
    }

    const href = buildDepotAnalysisHref(
      facility.facility_id,
      scenario.horizon_start,
      scenario.horizon_end,
      scenario.scenario_id,
      pinnedRunId,
      networkReturn,
    )
    if (href) {
      navigate(href)
      return
    }

    setSelectedFacilityId(facilityId)
    setSelectedLaneId(null)
  }
  const cards = [
    {
      label: 'Assigned cases',
      value: formatNumber(overview.kpis.assigned_units),
      delta: `${signedNumber(deltas.assigned_units)} cases`,
      tone: deltas.assigned_units >= 0 ? ('good' as const) : ('bad' as const),
    },
    {
      label: 'Unmet cases',
      value: formatNumber(overview.kpis.unmet_units),
      delta: `${signedNumber(deltas.unmet_units)} cases`,
      tone: deltas.unmet_units <= 0 ? ('good' as const) : ('bad' as const),
    },
    {
      label: 'Total cost',
      value: formatCurrency(overview.kpis.total_cost),
      delta: signedCurrency(deltas.total_cost),
      tone: deltas.total_cost <= 0 ? ('good' as const) : ('neutral' as const),
    },
    {
      label: 'Cost / case',
      value: formatCurrency(overview.kpis.cost_per_unit, 2),
      delta: signedCurrency(deltas.cost_per_unit, 2),
      tone: 'neutral' as const,
    },
    {
      label: 'On-time',
      value: formatPercent(overview.kpis.on_time_pct),
      delta: `${deltas.on_time_pct >= 0 ? '+' : ''}${formatNumber(deltas.on_time_pct, 1)} pts`,
      tone: deltas.on_time_pct >= 0 ? ('good' as const) : ('bad' as const),
    },
    {
      label: 'Lane utilization',
      value: formatPercent(overview.kpis.utilization_pct),
      delta: `${deltas.utilization_pct >= 0 ? '+' : ''}${formatNumber(deltas.utilization_pct, 1)} pts`,
      tone: 'neutral' as const,
    },
    {
      label: 'Depots with changed flow',
      value: formatNumber(result.data.affected_depot_ids.length),
      tone: 'default' as const,
    },
  ]

  return (
    <div className="flex flex-col gap-4">
      <div className="grid grid-cols-2 gap-3 sm:grid-cols-3 lg:grid-cols-4 xl:grid-cols-7">
        {cards.map((card) => (
          <KpiCard
            key={card.label}
            label={card.label}
            value={card.value}
            delta={card.delta}
            tone={card.tone}
          />
        ))}
      </div>
      {deltas.assigned_units === 0 && overview.kpis.unmet_units === 0 && (
        <p className="text-xs text-muted-foreground">
          All {formatNumber(overview.kpis.demand_units)} cases of demand are assigned in both
          plans, so assigned volume and cost per case have almost nothing to move. This
          scenario changes where cases are assigned, which is why the tariff and cross-border
          lines carry the signal.
        </p>
      )}
      <div className="grid overflow-hidden rounded-lg border border-border bg-card sm:grid-cols-2 lg:grid-cols-5">
        <CompactMetric label="Tariff paid" value={tariffTotal == null ? '—' : formatCurrency(tariffTotal)} />
        <CompactMetric label="Tariff if baseline unchanged" value={baselineTariffExposure == null ? '—' : formatCurrency(baselineTariffExposure)} />
        <CompactMetric
          label={tariffDifference != null && tariffDifference < 0 ? 'Added tariff exposure' : 'Tariff avoided'}
          value={tariffDifference == null ? '—' : formatCurrency(Math.abs(tariffDifference))}
        />
        <CompactMetric label="Cross-border cases" value={crossBorderCases == null ? '—' : formatNumber(crossBorderCases)} />
        <CompactMetric label="Cases shifted domestic" value={domesticShift == null ? '—' : formatNumber(domesticShift)} />
      </div>
      {(tariffTotal == null || baselineTariffExposure == null || crossBorderCases == null || domesticShift == null) && (
        <div className="rounded-md border border-amber-500/40 bg-amber-500/5 px-3 py-2 text-xs text-amber-700 dark:text-amber-400">
          This plan was generated before tariff metrics were available. Rerun the plan to see them.
        </div>
      )}
      <p className="text-xs text-muted-foreground">
        Scenario vs. source baseline · plan generated{' '}
        {new Date(result.data.generated_at).toLocaleString()} · baseline demand{' '}
        {formatNumber(baseline_overview.kpis.demand_units)} cases
      </p>
      <NetworkBaselineActions runId={pinnedRunId} />
      {(scenario.assumptions.tariffs ?? []).length > 0 && (
        <p className="text-xs text-muted-foreground">
          Applied tariff: {(scenario.assumptions.tariffs ?? []).map((rule) =>
            `${rule.origin_country} → ${rule.destination_country} · ${rule.amount_per_case.toLocaleString(undefined, { style: 'currency', currency: 'USD', minimumFractionDigits: 2, maximumFractionDigits: 2 })} / case`
          ).join('; ')}
        </p>
      )}
      {tariffTotal === 0 && (baselineTariffExposure ?? 0) > 0 && (
          <p className="rounded-md border border-border bg-muted/40 px-3 py-2 text-xs text-muted-foreground">
            The solver rerouted all tariff-eligible cases. It paid no tariff and avoided {formatCurrency(baselineTariffExposure ?? 0)} that the unchanged baseline would incur. A higher tariff alone will not change this allocation.
          </p>
        )}
      <div className="grid min-h-0 gap-4 xl:h-[calc(100svh-20rem)] xl:min-h-[720px] xl:grid-cols-[minmax(0,1fr)_340px]">
        <NetworkFlowMap
          facilities={overview.facilities}
          lanes={overview.lanes}
          selectedFacilityId={selectedFacilityId}
          selectedLaneId={selectedLaneId}
          onSelectFacility={openFacility}
          onSelectLane={(id) => {
            setSelectedLaneId(id)
            setSelectedFacilityId(null)
          }}
        />
        <div className="rounded-lg border border-border bg-card p-4">
          <h2 className="text-sm font-semibold">Baseline vs. scenario</h2>
          <ul className="mt-2 flex flex-col gap-2 text-sm">
            <CompareRow
              label="Assigned cases"
              baseline={formatNumber(baseline_overview.kpis.assigned_units)}
              scenario={formatNumber(overview.kpis.assigned_units)}
            />
            <CompareRow
              label="Unmet cases"
              baseline={formatNumber(baseline_overview.kpis.unmet_units)}
              scenario={formatNumber(overview.kpis.unmet_units)}
            />
            <CompareRow
              label="Total cost"
              baseline={formatCurrency(baseline_overview.kpis.total_cost)}
              scenario={formatCurrency(overview.kpis.total_cost)}
            />
            <CompareRow
              label="Tariff paid"
              baseline={formatCurrency(0)}
              scenario={tariffTotal == null ? 'Not provided' : formatCurrency(tariffTotal)}
            />
            <CompareRow
              label="Cross-border cases"
              baseline={result.data.baseline_cross_border_assigned_units == null
                ? '—'
                : formatNumber(result.data.baseline_cross_border_assigned_units)}
              scenario={crossBorderCases == null ? 'Not provided' : formatNumber(crossBorderCases)}
            />
            <CompareRow
              label="Cases shifted domestic"
              baseline={formatNumber(0)}
              scenario={domesticShift == null ? 'Not provided' : formatNumber(domesticShift)}
            />
            <CompareRow
              label="On-time"
              baseline={formatPercent(baseline_overview.kpis.on_time_pct)}
              scenario={formatPercent(overview.kpis.on_time_pct)}
            />
          </ul>
          {(baselineTariffExposure ?? 0) > 0 && (
            <p className="mt-3 text-xs text-muted-foreground">
              Unchanged baseline tariff exposure: {formatCurrency(baselineTariffExposure ?? 0)}. This counterfactual charge is not included in baseline total cost.
            </p>
          )}
          <p className="mt-4 text-xs text-muted-foreground">
            The solver assigns fixed demand through fixed supplied capacity; any
            remaining gap is reported as unmet demand, never absorbed.
          </p>
        </div>
      </div>
      <NetworkDetailDrawer
        facility={selectedFacility}
        lane={selectedLane}
        facilities={facilities}
        unmetByFacility={unmetByFacility}
        depotAnalysisHref={
          selectedFacility?.depot_analysis_available
            ? buildDepotAnalysisHref(
                selectedFacility.facility_id,
                scenario.horizon_start,
                scenario.horizon_end,
                scenario.scenario_id,
                pinnedRunId,
                networkReturn,
              )
            : null
        }
        dcAnalysisHref={
          selectedFacility?.facility_type === 'distribution_center'
            ? buildRouteWorkspaceHref(
                `/dc/${encodeURIComponent(selectedFacility.facility_id)}`,
                {
                  networkScenario: scenario.scenario_id,
                  networkRun: pinnedRunId,
                  networkReturn,
                },
              )
            : null
        }
        onClose={() => {
          setSelectedLaneId(null)
          setSelectedFacilityId(null)
        }}
        onSelectFacility={openFacility}
      />
    </div>
  )
}

function CompactMetric({ label, value }: { label: string; value: string }) {
  return (
    <div className="flex items-center justify-between gap-3 border-b border-border/60 px-3 py-2 last:border-0 sm:border-b-0 sm:border-r sm:last:border-r-0">
      <span className="text-xs text-muted-foreground">{label}</span>
      <span className="text-sm font-semibold tabular-nums">{value}</span>
    </div>
  )
}

function CompareRow({
  label,
  baseline,
  scenario,
}: {
  label: string
  baseline: string
  scenario: string
}) {
  return (
    <li className="flex items-center justify-between gap-2 border-b border-border/50 pb-1.5 last:border-0">
      <span className="text-muted-foreground">{label}</span>
      <span className="flex items-center gap-2 tabular-nums">
        <span className="text-muted-foreground">{baseline}</span>
        <span className="text-muted-foreground/60">→</span>
        <span className="font-medium text-primary">{scenario}</span>
      </span>
    </li>
  )
}

function signedNumber(value: number) {
  return `${value >= 0 ? '+' : ''}${formatNumber(value)}`
}

function signedCurrency(value: number, maximumFractionDigits = 0) {
  return `${value >= 0 ? '+' : ''}${formatCurrency(value, maximumFractionDigits)}`
}

/* ----------------------------- Lane changes tab ---------------------------- */

function LaneChangesTab({
  result,
  onBackToScenario,
}: {
  result: ResultQuery
  onBackToScenario: () => void
}) {
  const rows = useMemo(() => {
    if (!result.data) return []
    const tariffByLane = new Map<string, number>()
    for (const detail of result.data.charge_details) {
      if (detail.tariff_total == null) continue
      tariffByLane.set(detail.lane_id, (tariffByLane.get(detail.lane_id) ?? 0) + detail.tariff_total)
    }
    const baselineByLane = new Map(
      result.data.baseline_overview.lanes.map((lane) => [lane.lane_id, lane]),
    )
    return result.data.overview.lanes
      .map((lane) => {
        const base = baselineByLane.get(lane.lane_id)
        const baselineUnits = base?.assigned_units ?? 0
        return {
          lane,
          baselineUnits,
          delta: lane.assigned_units - baselineUnits,
          baselineCost: base?.total_cost ?? 0,
          tariffTotal: tariffByLane.get(lane.lane_id),
        }
      })
      .filter((row) => row.delta !== 0 || row.lane.total_cost !== row.baselineCost)
      .sort((a, b) => Math.abs(b.delta) - Math.abs(a.delta))
  }, [result.data])

  if (result.isLoading) {
    return (
      <div className="flex h-72 items-center justify-center text-muted-foreground">
        <Loader2 className="mr-2 h-4 w-4 animate-spin" /> Loading lane changes...
      </div>
    )
  }
  if (result.error || !result.data) {
    return (
      <EmptyState
        title="No plan results yet"
        description="Run the fixed-capacity plan to compare lane-level flow."
        action={{ label: 'Go to Scenario tab', onClick: onBackToScenario }}
      />
    )
  }
  if (!rows.length) {
    return (
      <EmptyState
        title="No lane flow changed"
        description="This scenario reproduces the published baseline flow on every lane."
      />
    )
  }

  return (
    <section className="overflow-hidden rounded-lg border border-border bg-card">
      <div className="border-b border-border/70 px-4 py-2.5 text-sm font-medium">
        {rows.length} lanes with changed assigned flow or cost
      </div>
      <div className="max-h-[560px] overflow-auto">
        <table className="w-full text-sm">
          <thead className="sticky top-0 bg-card">
            <tr className="border-b border-border/70 text-left text-xs uppercase tracking-wide text-muted-foreground">
              <th className="px-4 py-2 font-medium">Lane</th>
              <th className="px-4 py-2 font-medium">Type</th>
              <th className="px-4 py-2 text-right font-medium">Baseline</th>
              <th className="px-4 py-2 text-right font-medium">Scenario</th>
              <th className="px-4 py-2 text-right font-medium">Δ cases</th>
              <th className="px-4 py-2 text-right font-medium">Scenario cost</th>
              <th className="px-4 py-2 text-right font-medium">Tariff</th>
            </tr>
          </thead>
          <tbody className="divide-y divide-border/60">
            {rows.slice(0, 100).map((row) => (
              <tr key={row.lane.lane_id} className="hover:bg-accent/40">
                <td className="max-w-72 truncate px-4 py-2.5" title={row.lane.lane_name}>
                  {row.lane.lane_name}
                </td>
                <td className="px-4 py-2.5 text-xs uppercase tracking-wide text-muted-foreground">
                  {row.lane.lane_type}
                </td>
                <td className="px-4 py-2.5 text-right tabular-nums text-muted-foreground">
                  {formatNumber(row.baselineUnits)}
                </td>
                <td className="px-4 py-2.5 text-right font-medium tabular-nums">
                  {formatNumber(row.lane.assigned_units)}
                </td>
                <td
                  className={cn(
                    'px-4 py-2.5 text-right font-medium tabular-nums',
                    row.delta > 0
                      ? 'text-emerald-600 dark:text-emerald-400'
                      : 'text-destructive',
                  )}
                >
                  {signedNumber(row.delta)}
                </td>
                <td className="px-4 py-2.5 text-right tabular-nums">
                  {formatCurrency(row.lane.total_cost)}
                </td>
                <td className="px-4 py-2.5 text-right tabular-nums">
                  {row.tariffTotal == null ? (
                    <span className="text-xs text-muted-foreground" title="tariff_total was not provided by the API">Not provided</span>
                  ) : formatCurrency(row.tariffTotal)}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      {rows.length > 100 && (
        <div className="border-t border-border/70 px-4 py-2 text-xs text-muted-foreground">
          Showing the 100 largest changes of {rows.length}.
        </div>
      )}
    </section>
  )
}

/* ------------------------------ Rate audit tab ----------------------------- */

function RateAuditTab({
  result,
  onBackToScenario,
}: {
  result: ResultQuery
  onBackToScenario: () => void
}) {
  const [query, setQuery] = useState('')
  const [expanded, setExpanded] = useState<string | null>(null)

  const rows = useMemo(() => {
    if (!result.data) return []
    const needle = query.trim().toLowerCase()
    const filtered = needle
      ? result.data.charge_details.filter(
          (row) =>
            row.lane_id.toLowerCase().includes(needle) ||
            (row.contract_id ?? '').toLowerCase().includes(needle),
        )
      : result.data.charge_details
    return [...filtered]
      .sort((a, b) => b.total_cost - a.total_cost)
      .slice(0, 100)
  }, [result.data, query])

  if (result.isLoading) {
    return (
      <div className="flex h-72 items-center justify-center text-muted-foreground">
        <Loader2 className="mr-2 h-4 w-4 animate-spin" /> Loading rate audit...
      </div>
    )
  }
  if (result.error || !result.data) {
    return (
      <EmptyState
        title="No plan results yet"
        description="Run the fixed-capacity plan to audit governed rate charges."
        action={{ label: 'Go to Scenario tab', onClick: onBackToScenario }}
      />
    )
  }

  const governed = result.data.charge_details.filter(
    (row) => row.rate_source === 'governed_contract',
  ).length
  const fallback = result.data.charge_details.length - governed

  return (
    <div className="flex flex-col gap-3">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <p className="text-sm text-muted-foreground">
          {formatNumber(governed)} governed contract charges · {formatNumber(fallback)}{' '}
          planning-fallback charges (see Exceptions)
        </p>
        <label className="relative">
          <Search className="absolute left-2.5 top-1/2 h-3.5 w-3.5 -translate-y-1/2 text-muted-foreground" />
          <input
            value={query}
            onChange={(event) => setQuery(event.target.value)}
            placeholder="Filter by lane or contract"
            className="h-9 w-64 rounded-md border border-border bg-background pl-8 pr-3 text-sm"
          />
        </label>
      </div>
      <section className="overflow-hidden rounded-lg border border-border bg-card">
        <div className="max-h-[600px] overflow-auto">
          <table className="w-full text-sm">
            <thead className="sticky top-0 bg-card">
              <tr className="border-b border-border/70 text-left text-xs uppercase tracking-wide text-muted-foreground">
                <th className="px-4 py-2 font-medium">Service date</th>
                <th className="px-4 py-2 font-medium">Lane</th>
                <th className="px-4 py-2 text-right font-medium">Cases</th>
                <th className="px-4 py-2 text-right font-medium">Loads</th>
                <th className="px-4 py-2 font-medium">Rate source</th>
                <th className="px-4 py-2 font-medium">Contract</th>
                <th className="px-4 py-2 text-right font-medium">Cost</th>
                <th className="px-4 py-2 text-right font-medium">Tariff</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-border/60">
              {rows.map((row) => (
                <ChargeRow
                  key={`${row.service_date}-${row.lane_id}`}
                  row={row}
                  expanded={expanded === `${row.service_date}-${row.lane_id}`}
                  onToggle={() =>
                    setExpanded(
                      expanded === `${row.service_date}-${row.lane_id}`
                        ? null
                        : `${row.service_date}-${row.lane_id}`,
                    )
                  }
                />
              ))}
              {!rows.length && (
                <tr>
                  <td colSpan={8} className="px-4 py-8 text-center text-muted-foreground">
                    No charge details match this filter.
                  </td>
                </tr>
              )}
            </tbody>
          </table>
        </div>
      </section>
    </div>
  )
}

function ChargeRow({
  row,
  expanded,
  onToggle,
}: {
  row: NetworkFlowChargeDetail
  expanded: boolean
  onToggle: () => void
}) {
  return (
    <>
      <tr className="cursor-pointer hover:bg-accent/40" onClick={onToggle}>
        <td className="whitespace-nowrap px-4 py-2.5 tabular-nums text-muted-foreground">
          {row.service_date}
        </td>
        <td className="max-w-72 truncate px-4 py-2.5" title={row.lane_id}>
          {row.lane_id}
        </td>
        <td className="px-4 py-2.5 text-right tabular-nums">
          {formatNumber(row.assigned_units)}
        </td>
        <td className="px-4 py-2.5 text-right tabular-nums">{row.loads}</td>
        <td className="px-4 py-2.5">
          <span
            className={cn(
              'rounded-full px-2 py-0.5 text-[10px] font-medium',
              row.rate_source === 'governed_contract'
                ? 'bg-primary/15 text-primary'
                : 'bg-amber-500/10 text-amber-600 dark:text-amber-400',
            )}
          >
            {row.rate_source === 'governed_contract' ? 'Governed contract' : 'Planning fallback'}
          </span>
        </td>
        <td className="px-4 py-2.5 text-xs text-muted-foreground">
          {row.contract_id ?? '—'}
        </td>
        <td className="px-4 py-2.5 text-right font-medium tabular-nums">
          {formatCurrency(row.total_cost)}
        </td>
        <td className="px-4 py-2.5 text-right tabular-nums">
          {row.tariff_total == null ? (
            <span className="text-xs text-muted-foreground" title="tariff_total was not provided by the API">Not provided</span>
          ) : formatCurrency(row.tariff_total)}
        </td>
      </tr>
      {expanded && (
        <tr className="bg-muted/30">
          <td colSpan={8} className="px-4 py-3">
            <div className="flex flex-col gap-1.5 text-xs">
              {row.charge_lines.map((line, index) => (
                <div
                  key={`${line.rule_id}-${index}`}
                  className="flex flex-wrap items-center justify-between gap-2 border-b border-border/40 pb-1 last:border-0"
                >
                  <span className="font-medium">{line.label}</span>
                  <span className="text-muted-foreground">{line.formula}</span>
                  <span className="font-medium tabular-nums">
                    {formatCurrency(line.amount)}
                  </span>
                </div>
              ))}
              {row.rate_book_snapshot_id && (
                <div className="mt-1 text-muted-foreground">
                  Rate-book snapshot {row.rate_book_snapshot_id}
                </div>
              )}
              {row.tariff_rule_ids?.length ? (
                <div className="mt-1 text-muted-foreground">
                  Applied tariff rules: {row.tariff_rule_ids.join(', ')}
                </div>
              ) : null}
            </div>
          </td>
        </tr>
      )}
    </>
  )
}

/* ----------------------------- Exceptions tab ------------------------------ */

function ExceptionsTab({
  result,
  facilities,
  onBackToScenario,
}: {
  result: ResultQuery
  facilities: { facility_id: string; facility_name: string }[]
  onBackToScenario: () => void
}) {
  const [showAllMissingRates, setShowAllMissingRates] = useState(false)

  if (result.isLoading) {
    return (
      <div className="flex h-72 items-center justify-center text-muted-foreground">
        <Loader2 className="mr-2 h-4 w-4 animate-spin" /> Loading exceptions...
      </div>
    )
  }
  if (result.error || !result.data) {
    return (
      <EmptyState
        title="No plan results yet"
        description="Run the fixed-capacity plan to surface unmet demand and rate gaps."
        action={{ label: 'Go to Scenario tab', onClick: onBackToScenario }}
      />
    )
  }

  const exceptions = result.data.exceptions
  const unmet = exceptions.filter((row) => row.exception_type === 'unmet_demand')
  const missingRates = exceptions.filter((row) => row.exception_type === 'missing_rate')
  const unmetByDepot = new Map<string, NetworkScenarioException>()
  for (const row of unmet) {
    const key = row.entity_id ?? 'unknown'
    const existing = unmetByDepot.get(key)
    if (existing) {
      unmetByDepot.set(key, {
        ...existing,
        demand_units: (existing.demand_units ?? 0) + (row.demand_units ?? 0),
        assigned_units: (existing.assigned_units ?? 0) + (row.assigned_units ?? 0),
        unmet_units: (existing.unmet_units ?? 0) + (row.unmet_units ?? 0),
      })
    } else {
      unmetByDepot.set(key, { ...row })
    }
  }

  return (
    <div className="flex flex-col gap-4">
      {unmet.length === 0 && missingRates.length === 0 ? (
        <EmptyState
          title="No exceptions"
          description="Every case was assigned within supplied capacity and governed rates."
        />
      ) : (
        <>
          {unmet.length > 0 && (
            <section className="overflow-hidden rounded-lg border border-destructive/40 bg-destructive/5">
              <div className="flex items-center gap-2 border-b border-destructive/30 px-4 py-2.5 text-sm font-semibold text-destructive">
                <AlertTriangle className="h-4 w-4" />
                Unmet demand by depot (horizon total)
              </div>
              <table className="w-full text-sm">
                <thead>
                  <tr className="border-b border-border/60 text-left text-xs uppercase tracking-wide text-muted-foreground">
                    <th className="px-4 py-2 font-medium">Depot</th>
                    <th className="px-4 py-2 text-right font-medium">Demand</th>
                    <th className="px-4 py-2 text-right font-medium">Assigned</th>
                    <th className="px-4 py-2 text-right font-medium">Unmet</th>
                  </tr>
                </thead>
                <tbody className="divide-y divide-border/50 bg-card/60">
                  {[...unmetByDepot.values()]
                    .sort((a, b) => (b.unmet_units ?? 0) - (a.unmet_units ?? 0))
                    .map((row) => (
                      <tr key={row.exception_id + row.entity_id}>
                        <td className="px-4 py-2.5">
                          {facilities.find((f) => f.facility_id === row.entity_id)
                            ?.facility_name ?? row.entity_id}
                        </td>
                        <td className="px-4 py-2.5 text-right tabular-nums text-muted-foreground">
                          {formatNumber(row.demand_units ?? 0)}
                        </td>
                        <td className="px-4 py-2.5 text-right tabular-nums">
                          {formatNumber(row.assigned_units ?? 0)}
                        </td>
                        <td className="px-4 py-2.5 text-right font-semibold tabular-nums text-destructive">
                          {formatNumber(row.unmet_units ?? 0)}
                        </td>
                      </tr>
                    ))}
                </tbody>
              </table>
            </section>
          )}
          {missingRates.length > 0 && (
            <section className="overflow-hidden rounded-lg border border-amber-500/40 bg-amber-500/5">
              <div className="flex items-center gap-2 border-b border-amber-500/30 px-4 py-2.5 text-sm font-semibold text-amber-600 dark:text-amber-400">
                <Ban className="h-4 w-4" />
                Lanes without a published canonical rate ({missingRates.length})
              </div>
              <ul className="divide-y divide-border/50 bg-card/60">
                {(showAllMissingRates ? missingRates : missingRates.slice(0, 8)).map(
                  (row) => (
                    <li
                      key={row.exception_id}
                      className="flex flex-wrap items-center justify-between gap-2 px-4 py-2 text-sm"
                    >
                      <span className="min-w-0 flex-1 truncate" title={row.entity_id ?? undefined}>
                        {row.entity_id}
                      </span>
                      <span className="text-xs text-muted-foreground">
                        Planning fallback charge lines stored for audit
                      </span>
                    </li>
                  ),
                )}
              </ul>
              {missingRates.length > 8 && (
                <button
                  type="button"
                  onClick={() => setShowAllMissingRates(!showAllMissingRates)}
                  className="w-full border-t border-amber-500/30 px-4 py-2 text-xs font-medium text-amber-600 hover:bg-amber-500/10 dark:text-amber-400"
                >
                  {showAllMissingRates ? 'Show fewer' : `Show all ${missingRates.length}`}
                </button>
              )}
            </section>
          )}
        </>
      )}
    </div>
  )
}
