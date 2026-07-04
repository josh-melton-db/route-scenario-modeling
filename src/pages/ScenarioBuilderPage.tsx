import { useMemo, useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { Loader2, Play } from 'lucide-react'
import ConstraintPanel from '@/components/ConstraintPanel'
import DepotDayFilter from '@/components/DepotDayFilter'
import ErrorState from '@/components/ErrorState'
import ParameterForm from '@/components/ParameterForm'
import ScenarioTypePicker from '@/components/ScenarioTypePicker'
import {
  useCreateScenario,
  useDays,
  useDepots,
  useScenarioTypes,
  useStartRun,
  useValidateScenario,
} from '@/api/queries'
import type { ScenarioTypeSpec } from '@/api/types'
import {
  useScenarioDraft,
  type ScenarioDraftState,
} from '@/state/useScenarioDraft'

export default function ScenarioBuilderPage() {
  const navigate = useNavigate()
  const [submitError, setSubmitError] = useState<string | null>(null)
  const depots = useDepots()
  const days = useDays()
  const scenarioTypes = useScenarioTypes()
  const createScenario = useCreateScenario()
  const validateScenario = useValidateScenario()
  const startRun = useStartRun()
  const draft = useScenarioDraft()

  const selectedSpec = useMemo(
    () =>
      scenarioTypes.data?.find(
        (spec) => spec.scenario_type === draft.scenario_type,
      ) ?? null,
    [draft.scenario_type, scenarioTypes.data],
  )

  const error = depots.error ?? days.error ?? scenarioTypes.error
  if (error) return <ErrorState title="Could not load scenario builder" error={error} />

  const loading = depots.isLoading || days.isLoading || scenarioTypes.isLoading
  const busy =
    createScenario.isPending || validateScenario.isPending || startRun.isPending

  async function handleRun() {
    if (!draft.scenario_type) {
      setSubmitError('Choose a scenario type first.')
      return
    }
    setSubmitError(null)
    try {
      const created = await createScenario.mutateAsync({
        scenario_name: draft.scenario_name.trim() || selectedSpec?.label || 'Scenario',
        scenario_type: draft.scenario_type,
        baseline_scenario_id: 'baseline',
        depot_id: draft.depot_id,
        delivery_day: draft.delivery_day,
        parameters: draft.parameters,
      })
      const validation = await validateScenario.mutateAsync(
        created.scenario.scenario_id,
      )
      draft.setValidation(validation)
      if (!validation.valid) return
      const run = await startRun.mutateAsync(created.scenario.scenario_id)
      navigate(`/runs/${run.run_id}?scenarioId=${created.scenario.scenario_id}`)
    } catch (err) {
      setSubmitError(String(err))
    }
  }

  return (
    <div className="flex flex-col gap-5 px-4 py-5 sm:px-6 lg:px-8">
      <header className="flex flex-wrap items-end justify-between gap-4">
        <div>
          <h1 className="text-2xl font-semibold tracking-tight">
            Scenario builder
          </h1>
          <p className="mt-1 text-sm text-muted-foreground">
            Configure a what-if scenario for Generic Co and launch the served optimization run.
          </p>
        </div>
        <DepotDayFilter
          depots={depots.data ?? []}
          days={days.data ?? []}
          depotId={draft.depot_id}
          deliveryDay={draft.delivery_day}
          onChange={draft.setDepotDay}
        />
      </header>

      {loading ? (
        <div className="flex h-96 items-center justify-center text-muted-foreground">
          <Loader2 className="mr-2 h-4 w-4 animate-spin" />
          Loading scenario metadata...
        </div>
      ) : (
        <>
          <ScenarioTypePicker
            specs={scenarioTypes.data ?? []}
            selected={draft.scenario_type}
            onSelect={(spec) => selectScenarioType(spec, draft)}
          />

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
              {selectedSpec && (
                <ParameterForm
                  fields={selectedSpec.fields}
                  values={draft.parameters}
                  onChange={draft.setParameter}
                />
              )}
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
                disabled={busy || !draft.scenario_type}
                className="inline-flex items-center justify-center gap-2 rounded-md bg-primary px-4 py-2 text-sm font-semibold text-primary-foreground transition-colors disabled:cursor-not-allowed disabled:opacity-50"
              >
                {busy ? (
                  <Loader2 className="h-4 w-4 animate-spin" />
                ) : (
                  <Play className="h-4 w-4" />
                )}
                Validate and run
              </button>
            </div>
          </div>
        </>
      )}
    </div>
  )
}

function selectScenarioType(
  spec: ScenarioTypeSpec,
  draft: ScenarioDraftState,
) {
  draft.setScenarioType(spec.scenario_type)
  draft.setScenarioName(spec.label)
  draft.setParameters(
    Object.fromEntries(spec.fields.map((field) => [field.name, field.default])),
  )
}
