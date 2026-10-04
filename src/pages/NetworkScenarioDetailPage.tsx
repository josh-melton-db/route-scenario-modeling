import { useEffect, useMemo, useRef, useState } from 'react'
import { Navigate, useNavigate, useParams, useSearchParams } from 'react-router-dom'
import {
  AlertTriangle,
  ArrowRight,
  Ban,
  Check,
  Loader2,
  Pencil,
  Play,
  Plus,
  Search,
  Trash2,
  X,
} from 'lucide-react'
import EmptyState from '@/components/EmptyState'
import ErrorState from '@/components/ErrorState'
import KpiCard from '@/components/KpiCard'
import NetworkDetailDrawer from '@/components/NetworkDetailDrawer'
import NetworkFlowMap from '@/components/NetworkFlowMap'
import NetworkTariffChangeCard, {
  createNetworkTariffRule,
} from '@/components/NetworkTariffChangeCard'
import NetworkBaselineActions from '@/components/NetworkBaselineActions'
import NetworkPricingNote, { hasComparablePricing } from '@/components/NetworkPricingNote'
import {
  useDeleteNetworkScenario,
  useNetworkOptions,
  useNetworkOverview,
  useNetworkScenario,
  useNetworkScenarioResult,
  useNetworkRunCharges,
  useRunNetworkScenario,
  useUpdateNetworkScenario,
  useValidateNetworkScenario,
} from '@/api/queries'
import type {
  NetworkFlowChargeDetail,
  NetworkLaneAggregate,
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
  assumptions: NetworkScenarioAssumptions
  dirty: boolean
}

export default function NetworkScenarioDetailPage() {
  const { scenarioId = '', tab = 'scenario' } = useParams()
  const [searchParams, setSearchParams] = useSearchParams()
  const pinnedRunId = searchParams.get('run')
  const renameRequested = searchParams.get('rename') === '1'
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
  const [isEditingName, setIsEditingName] = useState(renameRequested)
  const [nameEditorValue, setNameEditorValue] = useState('')
  const [optimisticName, setOptimisticName] = useState<string | null>(null)
  const [saveState, setSaveState] = useState<'idle' | 'saving' | 'saved' | 'error'>('idle')
  const nameInputRef = useRef<HTMLInputElement>(null)

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

  useEffect(() => {
    if (renameRequested && scenario.data) {
      setNameEditorValue(scenario.data.scenario_name)
      setIsEditingName(true)
    }
  }, [renameRequested, scenario.data?.scenario_id])

  useEffect(() => {
    if (!isEditingName) return
    nameInputRef.current?.focus()
    nameInputRef.current?.select()
  }, [isEditingName])

  useEffect(() => {
    if (optimisticName && scenario.data?.scenario_name === optimisticName) {
      setOptimisticName(null)
    }
  }, [optimisticName, scenario.data?.scenario_name])

  useEffect(() => {
    if (!draft?.dirty || draft.scenarioId !== scenarioId) return
    const timer = window.setTimeout(() => {
      setSaveState('saving')
      void updateScenario
        .mutateAsync({
          expected_revision: scenario.data?.revision ?? 1,
          assumptions: draft.assumptions,
        })
        .then(() => {
          setDraft(null)
          setSaveState('saved')
        })
        .catch((err) => {
          setActionError(String(err))
          setSaveState('error')
        })
    }, 700)
    return () => window.clearTimeout(timer)
  }, [draft, scenarioId, updateScenario])

  useEffect(() => {
    if (saveState !== 'saved') return
    const timer = window.setTimeout(() => setSaveState('idle'), 2200)
    return () => window.clearTimeout(timer)
  }, [saveState])

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

  async function run() {
    setActionError(null)
    try {
      const pendingDraft = draft?.scenarioId === scenarioId && draft.dirty ? draft : null
      if (pendingDraft) {
        await updateScenario.mutateAsync({
          expected_revision: scenario.data!.revision,
          assumptions: pendingDraft.assumptions,
        })
        setDraft(null)
      }
      const validated = await validateScenario.mutateAsync()
      if (!validated.validation?.valid) {
        setActionError(validated.validation?.summary ?? 'Resolve validation errors before running the plan.')
        return
      }
      const completed = await runScenario.mutateAsync(validated.revision)
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

  function clearRenameHint() {
    if (!searchParams.has('rename')) return
    const next = new URLSearchParams(searchParams)
    next.delete('rename')
    setSearchParams(next, { replace: true })
  }

  function startEditingName() {
    setNameEditorValue(scenario.data?.scenario_name ?? '')
    setIsEditingName(true)
  }

  function cancelNameEdit() {
    setNameEditorValue(scenario.data?.scenario_name ?? '')
    setIsEditingName(false)
    clearRenameHint()
  }

  async function commitName() {
    if (!scenario.data) return
    const nextName = nameEditorValue.trim()
    if (!nextName || nextName === scenario.data.scenario_name) {
      cancelNameEdit()
      return
    }
    const previousName = scenario.data.scenario_name
    setActionError(null)
    setOptimisticName(nextName)
    try {
      await updateScenario.mutateAsync({
        expected_revision: scenario.data.revision,
        scenario_name: nextName,
      })
      setIsEditingName(false)
      clearRenameHint()
    } catch (err) {
      setOptimisticName(previousName)
      setActionError(String(err))
      requestAnimationFrame(() => nameInputRef.current?.focus())
    }
  }

  const displayName = optimisticName ?? scenario.data.scenario_name

  return (
    <div className="flex flex-col gap-5 px-4 py-5 sm:px-6 lg:px-8">
      {tab === 'scenario' && (
      <header>
        <div className="flex flex-wrap items-start justify-between gap-4">
          <div>
            <div className="flex flex-wrap items-center gap-2">
              {isEditingName ? (
                <form
                  onSubmit={(event) => {
                    event.preventDefault()
                    void commitName()
                  }}
                  className="flex min-w-0 items-center gap-1"
                >
                  <input
                    ref={nameInputRef}
                    aria-label="Network plan name"
                    value={nameEditorValue}
                    onChange={(event) => setNameEditorValue(event.target.value)}
                    onKeyDown={(event) => {
                      if (event.key === 'Escape') {
                        event.preventDefault()
                        cancelNameEdit()
                      }
                    }}
                    disabled={updateScenario.isPending}
                    className="h-9 min-w-56 rounded-md border border-border bg-background px-2 text-xl font-semibold tracking-tight text-foreground disabled:opacity-60"
                  />
                  <button
                    type="submit"
                    aria-label="Save network plan name"
                    disabled={updateScenario.isPending}
                    onMouseDown={(event) => event.preventDefault()}
                    className="inline-flex h-8 w-8 items-center justify-center rounded-md text-muted-foreground hover:bg-accent hover:text-foreground disabled:opacity-50"
                  >
                    {updateScenario.isPending ? (
                      <Loader2 className="h-4 w-4 animate-spin" />
                    ) : (
                      <Check className="h-4 w-4" />
                    )}
                  </button>
                  <button
                    type="button"
                    aria-label="Cancel network plan rename"
                    disabled={updateScenario.isPending}
                    onMouseDown={(event) => event.preventDefault()}
                    onClick={cancelNameEdit}
                    className="inline-flex h-8 w-8 items-center justify-center rounded-md text-muted-foreground hover:bg-accent hover:text-foreground disabled:opacity-50"
                  >
                    <X className="h-4 w-4" />
                  </button>
                </form>
              ) : (
                <div className="flex min-w-0 items-center gap-1">
                  <h1 className="truncate text-2xl font-semibold tracking-tight">
                    {displayName}
                  </h1>
                  <button
                    type="button"
                    aria-label="Rename network plan"
                    onClick={startEditingName}
                    className="inline-flex h-8 w-8 shrink-0 items-center justify-center rounded-md text-muted-foreground hover:bg-accent hover:text-foreground"
                  >
                    <Pencil className="h-4 w-4" />
                  </button>
                  <button
                    type="button"
                    aria-label="Delete network plan"
                    onClick={() => void handleDelete()}
                    disabled={busy || deleteScenario.isPending || scenario.data.status === 'published'}
                    className="inline-flex h-8 w-8 shrink-0 items-center justify-center rounded-md text-muted-foreground hover:bg-destructive/10 hover:text-destructive disabled:cursor-not-allowed disabled:opacity-50"
                  >
                    {deleteScenario.isPending ? (
                      <Loader2 className="h-4 w-4 animate-spin" />
                    ) : (
                      <Trash2 className="h-4 w-4" />
                    )}
                  </button>
                </div>
              )}
              <StatusPill scenario={scenario.data} />
            </div>
            <p className="mt-1 text-sm text-muted-foreground">
              {regionName(options.data.regions, scenario.data.region_id)} ·{' '}
              {scenario.data.horizon_start} → {scenario.data.horizon_end} · Revision{' '}
              {scenario.data.revision}
            </p>
          </div>
          <div className="flex flex-wrap items-center gap-3">
            {saveState === 'saving' && (
              <span className="inline-flex items-center gap-1.5 text-xs text-muted-foreground" aria-live="polite">
                <Loader2 className="h-3.5 w-3.5 animate-spin" />
                Saving…
              </span>
            )}
            {saveState === 'saved' && (
              <span className="inline-flex items-center gap-1.5 text-xs text-muted-foreground" aria-live="polite">
                <Check className="h-3.5 w-3.5" />
                Saved
              </span>
            )}
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
                disabled={busy || scenario.data.status === 'published' || scenario.data.validation?.valid === false}
                className="inline-flex h-10 items-center gap-2 rounded-md bg-primary px-4 text-sm font-semibold text-primary-foreground disabled:cursor-not-allowed disabled:opacity-50"
              >
                {busy ? (
                  <Loader2 className="h-4 w-4 animate-spin" />
                ) : (
                  <Play className="h-4 w-4" />
                )}
                {busy ? 'Running plan…' : 'Run fixed-capacity plan'}
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
}: {
  scenario: NetworkScenario
  draft: NetworkDraft | null
  onDraftChange: (draft: NetworkDraft | null) => void
  facilities: { facility_id: string; facility_name: string; facility_type: string; region_id: string }[]
  regions: { region_id: string; region_name: string }[]
  lanes: NetworkLaneAggregate[]
}) {
  const assumptions = draft?.assumptions ?? scenario.assumptions

  const disabledIds = new Set(assumptions.disabled_facility_ids)
  const disabledLaneIds = new Set(assumptions.disabled_lane_ids)
  const adjustedLaneIds = new Set(Object.keys(assumptions.lane_cost_adjustments_pct))
  const changedLaneIds = new Set([...disabledLaneIds, ...adjustedLaneIds])
  const [addLaneOriginId, setAddLaneOriginId] = useState('')
  const [addLaneDestinationId, setAddLaneDestinationId] = useState('')
  const [addLaneMode, setAddLaneMode] = useState<'disable' | 'adjust'>('disable')
  const [addAdjustPct, setAddAdjustPct] = useState('10')
  const [openConstraints, setOpenConstraints] = useState<
    Record<string, { facilities?: boolean; lanes?: boolean }>
  >({})
  const opened = openConstraints[scenario.scenario_id] ?? {}
  const hasFacilityConstraints = disabledIds.size > 0
  const hasLaneConstraints = changedLaneIds.size > 0
  const tariffs = assumptions.tariffs ?? []
  const hasTariffConstraints = tariffs.length > 0
  const showFacilityPicker = opened.facilities || hasFacilityConstraints
  const showLanePicker = opened.lanes || hasLaneConstraints
  const hasAnyConstraint =
    hasFacilityConstraints || hasLaneConstraints || hasTariffConstraints || showFacilityPicker || showLanePicker
  const availableLanes = lanes.filter((lane) => !changedLaneIds.has(lane.lane_id))
  const originOptions = uniqueLaneEndpoints(
    availableLanes.filter(
      (lane) =>
        !addLaneDestinationId ||
        lane.destination_endpoint_id === addLaneDestinationId,
    ),
    'origin_endpoint_id',
    'origin_endpoint_name',
  )
  const destinationOptions = uniqueLaneEndpoints(
    availableLanes.filter(
      (lane) =>
        !addLaneOriginId || lane.origin_endpoint_id === addLaneOriginId,
    ),
    'destination_endpoint_id',
    'destination_endpoint_name',
  )
  const selectedLane = availableLanes.find(
    (lane) =>
      lane.origin_endpoint_id === addLaneOriginId &&
      lane.destination_endpoint_id === addLaneDestinationId,
  )

  function touchAssumptions(next: NetworkScenarioAssumptions) {
    onDraftChange({ scenarioId: scenario.scenario_id, assumptions: next, dirty: true })
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

  function openConstraint(kind: 'facilities' | 'lanes') {
    setOpenConstraints((current) => ({
      ...current,
      [scenario.scenario_id]: {
        ...current[scenario.scenario_id],
        [kind]: true,
      },
    }))
  }

  function closeConstraint(kind: 'facilities' | 'lanes') {
    setOpenConstraints((current) => ({
      ...current,
      [scenario.scenario_id]: {
        ...current[scenario.scenario_id],
        [kind]: false,
      },
    }))
  }

  function addTariffRule() {
    touchAssumptions({
      ...assumptions,
      tariffs: [
        ...tariffs,
        createNetworkTariffRule(scenario.horizon_start, scenario.horizon_end),
      ],
    })
  }

  function clearFacilityConstraints() {
    if (hasFacilityConstraints) {
      touchAssumptions({ ...assumptions, disabled_facility_ids: [] })
    }
    closeConstraint('facilities')
  }

  function clearLaneConstraints() {
    if (hasLaneConstraints) {
      touchAssumptions({
        ...assumptions,
        disabled_lane_ids: [],
        lane_cost_adjustments_pct: {},
      })
    }
    closeConstraint('lanes')
  }

  function addLaneOverride() {
    const laneId = selectedLane?.lane_id
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
    setAddLaneOriginId('')
    setAddLaneDestinationId('')
  }

  const validation = scenario.validation

  return (
    <div className="flex flex-col gap-4">
      <section className="rounded-lg border border-border bg-card p-4">
        <h2 className="text-sm font-semibold">Starting plan</h2>
        <p className="mt-1 text-xs text-muted-foreground">
          Published baseline · demand {scenario.demand_plan_version_id} · capacity {scenario.capacity_plan_version_id} · {scenario.horizon_start} to {scenario.horizon_end}
        </p>
      </section>
      {hasTariffConstraints && (
        <NetworkTariffChangeCard
          rules={tariffs}
          onChange={(tariffs) => touchAssumptions({ ...assumptions, tariffs })}
        />
      )}
      <div className="grid gap-4 lg:grid-cols-[2fr_1fr]">
        <section className="flex flex-col gap-4 rounded-lg border border-border bg-card p-4">
          <div>
            <h2 className="text-sm font-semibold">Network changes</h2>
            <p className="mt-1 text-xs text-muted-foreground">
              Layer only the changes this scenario needs. All active changes are applied together when the plan runs.
            </p>
          </div>
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

          <div className="flex flex-wrap gap-2">
            <button
              type="button"
              onClick={addTariffRule}
              className="inline-flex items-center gap-1 rounded-md border border-border px-2.5 py-1.5 text-xs hover:bg-accent/40"
            >
              <Plus className="h-3.5 w-3.5" />
              Add tariff rule
            </button>
            {!showFacilityPicker && (
              <button
                type="button"
                onClick={() => openConstraint('facilities')}
                className="inline-flex items-center gap-1 rounded-md border border-border px-2.5 py-1.5 text-xs hover:bg-accent/40"
              >
                <Plus className="h-3.5 w-3.5" />
                Facility availability
              </button>
            )}
            {!showLanePicker && (
              <button
                type="button"
                onClick={() => openConstraint('lanes')}
                className="inline-flex items-center gap-1 rounded-md border border-border px-2.5 py-1.5 text-xs hover:bg-accent/40"
              >
                <Plus className="h-3.5 w-3.5" />
                Lane rule
              </button>
            )}
          </div>

          {!hasAnyConstraint && (
            <p className="rounded-md border border-dashed border-border p-3 text-xs text-muted-foreground">
              No network changes yet. Add a tariff, restrict facility availability, or layer a lane rule.
            </p>
          )}

          {showFacilityPicker && (
          <div className="flex flex-col gap-2 rounded-md border border-border/70 p-3">
            <div className="flex items-start justify-between gap-2">
              <div className="flex flex-col gap-1">
                <span className="text-sm font-semibold">Facility availability</span>
                <span className="text-xs text-muted-foreground">Disable DCs or depots while retaining published capacity for comparison.</span>
              </div>
              <button
                type="button"
                onClick={clearFacilityConstraints}
                className="inline-flex shrink-0 items-center gap-1 rounded-md border border-border px-2 py-1 text-xs text-muted-foreground hover:text-destructive"
              >
                <Trash2 className="h-3.5 w-3.5" />
                Remove
              </button>
            </div>
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
          )}

          {showLanePicker && (
          <div className="flex flex-col gap-2 rounded-md border border-border/70 p-3">
            <div className="flex items-start justify-between gap-2">
              <div className="flex flex-col gap-1">
                <span className="text-sm font-semibold">Lane rule</span>
                <span className="text-xs text-muted-foreground">Disable a linehaul lane or adjust its planning cost assumption.</span>
              </div>
              <button
                type="button"
                onClick={clearLaneConstraints}
                className="inline-flex shrink-0 items-center gap-1 rounded-md border border-border px-2 py-1 text-xs text-muted-foreground hover:text-destructive"
              >
                <Trash2 className="h-3.5 w-3.5" />
                Remove
              </button>
            </div>
            <div className="grid gap-2 md:grid-cols-[minmax(0,1fr)_minmax(0,1fr)_auto]">
              <label className="flex min-w-0 flex-col gap-1 text-xs text-muted-foreground">
                <span>From</span>
                <select
                  aria-label="Lane from"
                  value={addLaneOriginId}
                  onChange={(event) => {
                    const originId = event.target.value
                    setAddLaneOriginId(originId)
                    if (
                      originId &&
                      addLaneDestinationId &&
                      !availableLanes.some(
                        (lane) =>
                          lane.origin_endpoint_id === originId &&
                          lane.destination_endpoint_id === addLaneDestinationId,
                      )
                    ) {
                      setAddLaneDestinationId('')
                    }
                  }}
                  className="h-9 rounded-md border border-border bg-background px-2 text-sm text-foreground"
                >
                  <option value="">Select origin…</option>
                  {originOptions.map((option) => (
                    <option key={option.id} value={option.id}>
                      {option.name}
                    </option>
                  ))}
                </select>
              </label>
              <label className="flex min-w-0 flex-col gap-1 text-xs text-muted-foreground">
                <span>To</span>
                <select
                  aria-label="Lane to"
                  value={addLaneDestinationId}
                  onChange={(event) => {
                    const destinationId = event.target.value
                    setAddLaneDestinationId(destinationId)
                    if (
                      destinationId &&
                      addLaneOriginId &&
                      !availableLanes.some(
                        (lane) =>
                          lane.origin_endpoint_id === addLaneOriginId &&
                          lane.destination_endpoint_id === destinationId,
                      )
                    ) {
                      setAddLaneOriginId('')
                    }
                  }}
                  className="h-9 rounded-md border border-border bg-background px-2 text-sm text-foreground"
                >
                  <option value="">Select destination…</option>
                  {destinationOptions.map((option) => (
                    <option key={option.id} value={option.id}>
                      {option.name}
                    </option>
                  ))}
                </select>
              </label>
              <div className="flex flex-wrap items-end gap-2 md:flex-nowrap">
                <select
                  aria-label="Lane change type"
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
                  disabled={!selectedLane}
                  className="h-9 rounded-md border border-border bg-background px-3 text-sm font-medium hover:bg-accent/50 disabled:opacity-50"
                >
                  Add
                </button>
              </div>
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
          )}
        </section>

        <section className="flex flex-col gap-3 rounded-lg border border-border bg-card p-4">
          <h2 className="text-sm font-semibold">Plan checks</h2>
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
              Validation runs automatically before the plan is solved.
            </p>
          )}
          <p className="text-xs text-muted-foreground">
            Run fixed-capacity plan from the header. The app saves pending edits,
            validates the scenario, then solves.
          </p>
        </section>
      </div>
    </div>
  )
}

function uniqueLaneEndpoints(
  lanes: NetworkLaneAggregate[],
  idKey: 'origin_endpoint_id' | 'destination_endpoint_id',
  nameKey: 'origin_endpoint_name' | 'destination_endpoint_name',
) {
  const endpoints = new Map<string, { id: string; name: string }>()
  for (const lane of lanes) {
    endpoints.set(lane[idKey], { id: lane[idKey], name: lane[nameKey] })
  }
  return [...endpoints.values()].sort((left, right) =>
    left.name.localeCompare(right.name),
  )
}

function laneNameFor(lanes: NetworkLaneAggregate[], laneId: string) {
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
      label: 'Linehaul cost',
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
      <NetworkPricingNote result={result.data} />
      {deltas.assigned_units === 0 && overview.kpis.unmet_units === 0 && (
        <p className="text-xs text-muted-foreground">
          All {formatNumber(overview.kpis.demand_units)} cases of demand are assigned in both
          plans. Assigned volume is unchanged; freight and tariffs can still change as
          sourcing changes. Compare the linehaul cost, tariff, and cross-border lines.
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
              label="Linehaul cost"
              baseline={formatCurrency(baseline_overview.kpis.total_cost)}
              scenario={formatCurrency(overview.kpis.total_cost)}
            />
            <CompareRow
              label="Tariff paid"
              baseline={hasComparablePricing(result.data) ? formatCurrency(result.data.baseline_tariff_total_cost ?? 0) : 'Not recorded'}
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
              Unchanged baseline tariff exposure: {formatCurrency(baselineTariffExposure ?? 0)} under the scenario's tariff rules. This is a counterfactual; baseline cost includes only its existing tariffs.
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
          tariffTotal: lane.tariff_total,
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
  const [debouncedQuery, setDebouncedQuery] = useState('')
  const [pricingSide, setPricingSide] = useState<'scenario' | 'baseline'>('scenario')
  const [offset, setOffset] = useState(0)
  const [expanded, setExpanded] = useState<string | null>(null)
  const limit = 100
  const audit = useNetworkRunCharges(
    result.data?.run_id,
    pricingSide,
    offset,
    limit,
    debouncedQuery,
  )

  useEffect(() => {
    const timer = window.setTimeout(() => {
      setDebouncedQuery(query.trim())
      setOffset(0)
    }, 300)
    return () => window.clearTimeout(timer)
  }, [query])

  const rows = audit.data?.items ?? []

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

  const governed = audit.data?.coverage.governed_charge_count ?? 0
  const fallback = audit.data?.coverage.fallback_charge_count ?? 0

  return (
    <div className="flex flex-col gap-3">
      <NetworkPricingNote result={result.data} detailed />
      <div className="flex flex-wrap items-center justify-between gap-3">
        <p className="text-sm text-muted-foreground">
          {formatNumber(governed)} governed contract charges · {formatNumber(fallback)}{' '}
          planning-fallback charges (see Exceptions)
        </p>
        <label className="flex items-center gap-2 text-xs text-muted-foreground">
          Audit plan
          <select aria-label="Audit plan" value={pricingSide} onChange={(event) => { setPricingSide(event.target.value as 'scenario' | 'baseline'); setOffset(0); setExpanded(null) }} className="h-9 rounded-md border border-border bg-background px-2 text-sm text-foreground">
            <option value="scenario">Scenario</option>
            <option value="baseline" disabled={!hasComparablePricing(result.data)}>Comparable baseline</option>
          </select>
        </label>
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
        {audit.isLoading && (
          <div className="flex h-20 items-center justify-center text-sm text-muted-foreground">
            <Loader2 className="mr-2 h-4 w-4 animate-spin" /> Loading charge details...
          </div>
        )}
        {audit.error && (
          <div className="px-4 py-6 text-sm text-destructive">Could not load charge details: {String(audit.error)}</div>
        )}
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
      {audit.data && audit.data.total > 0 && (
        <div className="flex items-center justify-between text-sm text-muted-foreground">
          <span>
            Showing {formatNumber(offset + 1)}–{formatNumber(Math.min(offset + limit, audit.data.total))} of {formatNumber(audit.data.total)}
          </span>
          <div className="flex gap-2">
            <button type="button" className="rounded-md border border-border px-3 py-1.5 disabled:opacity-50" disabled={offset === 0 || audit.isFetching} onClick={() => setOffset(Math.max(0, offset - limit))}>Previous</button>
            <button type="button" className="rounded-md border border-border px-3 py-1.5 disabled:opacity-50" disabled={offset + limit >= audit.data.total || audit.isFetching} onClick={() => setOffset(offset + limit)}>Next</button>
          </div>
        </div>
      )}
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
