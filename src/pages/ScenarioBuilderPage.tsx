import { useEffect, useMemo, useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { GitBranch, GitCompareArrows, Loader2, Play, Trash2 } from 'lucide-react'
import ConstraintPanel from '@/components/ConstraintPanel'
import CustomScenarioBuilder from '@/components/CustomScenarioBuilder'
import DepotDayFilter from '@/components/DepotDayFilter'
import ErrorState from '@/components/ErrorState'
import ScenarioHistory from '@/components/ScenarioHistory'
import ScenarioCombobox from '@/components/ScenarioCombobox'
import {
  useBaselineNetwork,
  useCreateScenarioRun,
  useDeleteScenario,
  useDays,
  useDepots,
  useRecentScenarios,
} from '@/api/queries'
import type { CostOverride, DraftScenarioChange, ScenarioHistoryItem } from '@/api/types'
import { useScenarioDraft } from '@/state/useScenarioDraft'

export default function ScenarioBuilderPage() {
  const navigate = useNavigate()
  const [submitError, setSubmitError] = useState<string | null>(null)
  const [selectedScenarioId, setSelectedScenarioId] = useState('baseline')
  const [branchSourceId, setBranchSourceId] = useState<string | null>(null)
  const depots = useDepots()
  const days = useDays()
  const createScenarioRun = useCreateScenarioRun()
  const deleteScenario = useDeleteScenario()
  const scenarios = useRecentScenarios(50)
  const draft = useScenarioDraft()
  const baselineNetwork = useBaselineNetwork(draft.depot_id, draft.delivery_day)

  useEffect(() => {
    draft.reset()
  }, [draft.reset])

  const selectedDepot = useMemo(
    () =>
      depots.data?.find((depot) => depot.depot_id === draft.depot_id) ??
      baselineNetwork.data?.depot ??
      null,
    [baselineNetwork.data?.depot, depots.data, draft.depot_id],
  )

  const error = depots.error ?? days.error ?? scenarios.error
  if (error) return <ErrorState title="Could not load scenario builder" error={error} />

  const loading = depots.isLoading || days.isLoading
  const busy = createScenarioRun.isPending || deleteScenario.isPending

  function loadScenario(scenario: ScenarioHistoryItem) {
    const rawChanges = Array.isArray(scenario.parameters.changes)
      ? scenario.parameters.changes
      : []
    const changes = rawChanges
      .filter((change): change is Record<string, unknown> =>
        Boolean(change && typeof change === 'object' && 'kind' in change),
      )
      .map((change) => ({
        ...change,
        clientId: globalThis.crypto?.randomUUID?.() ?? `${scenario.scenario_id}-${Math.random()}`,
      })) as DraftScenarioChange[]
    const cost = scenario.parameters.cost
    const costOverride = cost && typeof cost === 'object' && !Array.isArray(cost)
      ? cost as CostOverride
      : {}

    draft.setScenarioName(scenario.scenario_name)
    draft.setDepotDay(scenario.depot_id, scenario.delivery_day)
    draft.setChanges(changes)
    draft.setCostOverride(costOverride)
    draft.setCostOverrideEnabled(Object.keys(costOverride).length > 0)
    draft.setValidation(null)
  }

  function handleScenarioSelection(scenarioId: string) {
    setSubmitError(null)
    setBranchSourceId(null)
    setSelectedScenarioId(scenarioId)
    if (scenarioId === 'baseline') {
      draft.reset()
      return
    }
    const scenario = scenarios.data?.find((item) => item.scenario_id === scenarioId)
    if (scenario) loadScenario(scenario)
  }

  async function handleDelete() {
    if (selectedScenarioId === 'baseline') return
    const selected = scenarios.data?.find((item) => item.scenario_id === selectedScenarioId)
    if (!window.confirm(`Delete “${selected?.scenario_name ?? 'this scenario'}”? This cannot be undone.`)) return
    setSubmitError(null)
    try {
      await deleteScenario.mutateAsync(selectedScenarioId)
      setSelectedScenarioId('baseline')
      setBranchSourceId(null)
      draft.reset()
    } catch (err) {
      setSubmitError(String(err))
    }
  }

  async function handleRun() {
    setSubmitError(null)
    draft.setValidation(null)
    try {
      const started = await createScenarioRun.mutateAsync({
        scenario_name: draft.scenario_name.trim() || 'Custom scenario',
        scenario_type: 'custom',
        baseline_scenario_id: branchSourceId ?? 'baseline',
        depot_id: draft.depot_id,
        delivery_day: draft.delivery_day,
        parameters: draft.buildParameters(),
      })
      if (started.validation) {
        draft.setValidation(started.validation)
        return
      }
      if (!started.run) {
        throw new Error('The scenario was created without a run to track.')
      }
      navigate(
        `/runs/${started.run.run_id}?scenarioId=${started.run.scenario_id}`,
      )
    } catch (err) {
      setSubmitError(String(err))
    }
  }

  return (
    <div className="flex flex-col gap-5 px-4 py-5 sm:px-6 lg:px-8">
      <div className="flex flex-wrap items-end justify-between gap-4">
        <div className="flex flex-wrap items-end gap-2">
          <ScenarioCombobox
            label="Starting point"
            value={selectedScenarioId}
            scenarios={scenarios.data ?? []}
            includeBaseline
            onChange={handleScenarioSelection}
          />
          {selectedScenarioId !== 'baseline' && (
            <>
              <button
                type="button"
                onClick={() => navigate(`/analyze?primary=${encodeURIComponent(selectedScenarioId)}&compare=baseline`)}
                className="inline-flex h-10 items-center gap-2 rounded-md border border-border bg-card px-3 text-sm font-medium hover:bg-accent/50"
              >
                <GitCompareArrows className="h-4 w-4" />
                Compare
              </button>
              {!branchSourceId && (
                <>
                  <button
                    type="button"
                    onClick={() => {
                      setBranchSourceId(selectedScenarioId)
                      draft.setScenarioName(`${draft.scenario_name} branch`)
                      draft.setValidation(null)
                    }}
                    className="inline-flex h-10 items-center gap-2 rounded-md border border-border bg-card px-3 text-sm font-medium hover:bg-accent/50"
                  >
                    <GitBranch className="h-4 w-4" />
                    Branch
                  </button>
                  <button
                    type="button"
                    onClick={handleDelete}
                    disabled={busy}
                    className="inline-flex h-10 items-center gap-2 rounded-md border border-destructive/50 px-3 text-sm font-medium text-destructive hover:bg-destructive/10 disabled:opacity-50"
                  >
                    <Trash2 className="h-4 w-4" />
                    Delete
                  </button>
                </>
              )}
            </>
          )}
        </div>
        <DepotDayFilter
          depots={depots.data ?? []}
          days={days.data ?? []}
          depotId={draft.depot_id}
          deliveryDay={draft.delivery_day}
          onChange={draft.setDepotDay}
        />
      </div>

      {branchSourceId && (
        <div className="flex items-center gap-2 rounded-md border border-primary/30 bg-primary/5 px-3 py-2 text-sm text-foreground">
          <GitBranch className="h-4 w-4 text-primary" />
          Creating a new scenario from {scenarios.data?.find((scenario) => scenario.scenario_id === branchSourceId)?.scenario_name ?? 'the selected scenario'}.
        </div>
      )}

      {loading ? (
        <div className="flex h-96 items-center justify-center text-muted-foreground">
          <Loader2 className="mr-2 h-4 w-4 animate-spin" />
          Loading scenario metadata...
        </div>
      ) : (
        <>
          <div className="grid gap-4 lg:grid-cols-[2fr_1fr]">
            <div className="flex flex-col gap-4">
              <div className="rounded-lg border border-border bg-card p-4">
                <label className="flex flex-col gap-1.5 text-sm">
                  <span className="font-medium">Scenario name</span>
                  <input
                    value={draft.scenario_name}
                    onChange={(event) => draft.setScenarioName(event.target.value)}
                    className="rounded-md border border-border bg-background px-3 py-2 text-sm text-foreground"
                  />
                </label>
              </div>
              <CustomScenarioBuilder
                depot={selectedDepot}
                baselineRoutes={baselineNetwork.data?.routes ?? []}
                changes={draft.changes}
                costOverride={draft.costOverride}
                costOverrideEnabled={draft.costOverrideEnabled}
                onChangesChange={draft.setChanges}
                onCostChange={draft.setCostOverride}
                onCostEnabledChange={draft.setCostOverrideEnabled}
              />
            </div>
            <div className="flex flex-col gap-4">
              <ConstraintPanel validation={draft.validation} />
              {submitError && (
                <div className="rounded-md border border-destructive/40 bg-destructive/10 p-3 text-sm text-destructive">
                  {submitError}
                </div>
              )}
              <button
                onClick={handleRun}
                disabled={busy}
                className="inline-flex items-center justify-center gap-2 rounded-md bg-primary px-4 py-2 text-sm font-semibold text-primary-foreground transition-colors disabled:cursor-not-allowed disabled:opacity-50"
              >
                {busy ? (
                  <Loader2 className="h-4 w-4 animate-spin" />
                ) : (
                  <Play className="h-4 w-4" />
                )}
                {branchSourceId ? 'Run branched scenario' : 'Run scenario'}
              </button>
              <ScenarioHistory />
            </div>
          </div>
        </>
      )}
    </div>
  )
}
