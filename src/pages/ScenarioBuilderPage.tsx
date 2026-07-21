import { useMemo, useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { Loader2, Play } from 'lucide-react'
import ConstraintPanel from '@/components/ConstraintPanel'
import CustomScenarioBuilder from '@/components/CustomScenarioBuilder'
import DepotDayFilter from '@/components/DepotDayFilter'
import ErrorState from '@/components/ErrorState'
import ScenarioHistory from '@/components/ScenarioHistory'
import {
  useBaselineNetwork,
  useCreateScenarioRun,
  useDays,
  useDepots,
} from '@/api/queries'
import { useScenarioDraft } from '@/state/useScenarioDraft'

export default function ScenarioBuilderPage() {
  const navigate = useNavigate()
  const [submitError, setSubmitError] = useState<string | null>(null)
  const depots = useDepots()
  const days = useDays()
  const createScenarioRun = useCreateScenarioRun()
  const draft = useScenarioDraft()
  const baselineNetwork = useBaselineNetwork(draft.depot_id, draft.delivery_day)

  const selectedDepot = useMemo(
    () =>
      depots.data?.find((depot) => depot.depot_id === draft.depot_id) ??
      baselineNetwork.data?.depot ??
      null,
    [baselineNetwork.data?.depot, depots.data, draft.depot_id],
  )

  const error = depots.error ?? days.error
  if (error) return <ErrorState title="Could not load scenario builder" error={error} />

  const loading = depots.isLoading || days.isLoading
  const busy = createScenarioRun.isPending

  async function handleRun() {
    setSubmitError(null)
    draft.setValidation(null)
    try {
      const started = await createScenarioRun.mutateAsync({
        scenario_name: draft.scenario_name.trim() || 'Custom scenario',
        scenario_type: 'custom',
        baseline_scenario_id: 'baseline',
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
      <div className="flex flex-wrap justify-end gap-4">
        <DepotDayFilter
          depots={depots.data ?? []}
          days={days.data ?? []}
          depotId={draft.depot_id}
          deliveryDay={draft.delivery_day}
          onChange={draft.setDepotDay}
        />
      </div>

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
                Run scenario
              </button>
              <ScenarioHistory />
            </div>
          </div>
        </>
      )}
    </div>
  )
}
