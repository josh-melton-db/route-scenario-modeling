import { useMemo, useState } from 'react'
import { Plus, Trash2 } from 'lucide-react'
import CostParameterForm from '@/components/CostParameterForm'
import DeliveryMapEditor from '@/components/DeliveryMapEditor'
import DeliveryUploadPanel from '@/components/DeliveryUploadPanel'
import type {
  CostOverride,
  Depot,
  DraftScenarioChange,
  LatLng,
  Route,
  ScenarioChange,
  ScenarioChangeKind,
} from '@/api/types'

interface CustomScenarioBuilderProps {
  depot: Depot | null
  baselineRoutes: Route[]
  changes: DraftScenarioChange[]
  costOverride: CostOverride
  costOverrideEnabled: boolean
  onChangesChange: (changes: DraftScenarioChange[]) => void
  onCostChange: (cost: CostOverride) => void
  onCostEnabledChange: (enabled: boolean) => void
}

const CHANGE_OPTIONS: Array<{ kind: ScenarioChangeKind; label: string }> = [
  { kind: 'add_deliveries', label: 'Add deliveries (map / upload)' },
  { kind: 'driver_count_change', label: 'Driver / truck count change' },
  { kind: 'delivery_frequency_day_change', label: 'Delivery day change' },
  { kind: 'facility_move', label: 'Facility / warehouse move' },
]

let nextClientId = 0

function createClientId() {
  nextClientId += 1
  return (
    globalThis.crypto?.randomUUID?.() ??
    `scenario-change-${Date.now()}-${nextClientId}`
  )
}

function defaultChange(
  kind: ScenarioChangeKind,
  depotLocation: LatLng,
): DraftScenarioChange {
  const clientId = createClientId()
  if (kind === 'add_deliveries') {
    return { clientId, kind, deliveries: [] }
  }
  if (kind === 'driver_count_change') {
    return { clientId, kind, driver_delta: -1, allow_overtime: true }
  }
  if (kind === 'delivery_frequency_day_change') {
    return {
      clientId,
      kind,
      target_day: 'Thursday',
      target_customers: 'flexible_independents',
    }
  }
  return {
    clientId,
    kind,
    new_depot_location: depotLocation,
    preserve_service_windows: true,
  }
}

export default function CustomScenarioBuilder({
  depot,
  baselineRoutes,
  changes,
  costOverride,
  costOverrideEnabled,
  onChangesChange,
  onCostChange,
  onCostEnabledChange,
}: CustomScenarioBuilderProps) {
  const [showUpload, setShowUpload] = useState(false)
  const depotLocation = useMemo<LatLng>(
    () => depot?.location ?? { lat: 42.3314, lng: -83.0458 },
    [depot],
  )

  function addChange(kind: ScenarioChangeKind) {
    if (changes.some((change) => change.kind === kind)) return
    onChangesChange([...changes, defaultChange(kind, depotLocation)])
  }

  function updateChange(clientId: string, patch: Partial<ScenarioChange>) {
    onChangesChange(
      changes.map((change) =>
        change.clientId === clientId ? { ...change, ...patch } : change,
      ),
    )
  }

  function removeChange(clientId: string) {
    onChangesChange(changes.filter((change) => change.clientId !== clientId))
  }

  const availableChangeOptions = CHANGE_OPTIONS.filter(
    (option) => !changes.some((change) => change.kind === option.kind),
  )

  return (
    <div className="flex flex-col gap-4">
      <div className="rounded-lg border border-border bg-card p-4">
        <div className="text-sm font-semibold">Stacked changes</div>
        <p className="mt-1 text-xs text-muted-foreground">
          Combine any set of changes into one custom scenario. Each selected
          option is available once and applied together when you run.
        </p>
        <div className="mt-3 flex flex-wrap gap-2">
          {availableChangeOptions.map((option) => (
            <button
              key={option.kind}
              type="button"
              onClick={() => addChange(option.kind)}
              className="inline-flex items-center gap-1 rounded-md border border-border px-2.5 py-1.5 text-xs hover:bg-accent/40"
            >
              <Plus className="h-3.5 w-3.5" />
              {option.label}
            </button>
          ))}
          {!costOverrideEnabled && (
            <button
              type="button"
              onClick={() => onCostEnabledChange(true)}
              className="inline-flex items-center gap-1 rounded-md border border-border px-2.5 py-1.5 text-xs hover:bg-accent/40"
            >
              <Plus className="h-3.5 w-3.5" />
              Cost parameters
            </button>
          )}
          {availableChangeOptions.length === 0 && costOverrideEnabled && (
            <span className="py-1.5 text-xs text-muted-foreground">
              All change cards are active.
            </span>
          )}
        </div>
      </div>

      {changes.length === 0 && !costOverrideEnabled && (
        <div className="rounded-lg border border-dashed border-border bg-card/40 p-4 text-sm text-muted-foreground">
          No changes yet. Add deliveries, adjust drivers, shift days, or move the
          facility. Cost parameters are optional.
        </div>
      )}

      {changes.map((change) => (
        <div key={change.clientId} className="rounded-lg border border-border bg-card p-4">
          <div className="mb-3 flex items-center justify-between gap-2">
            <div className="text-sm font-semibold">
              {CHANGE_OPTIONS.find((option) => option.kind === change.kind)?.label ??
                change.kind}
            </div>
            <button
              type="button"
              onClick={() => removeChange(change.clientId)}
              className="inline-flex items-center gap-1 rounded-md border border-border px-2 py-1 text-xs text-muted-foreground hover:text-destructive"
            >
              <Trash2 className="h-3.5 w-3.5" />
              Remove
            </button>
          </div>

          {change.kind === 'add_deliveries' && depot && (
            <div className="flex flex-col gap-3">
              <DeliveryMapEditor
                depot={depot}
                baselineRoutes={baselineRoutes}
                deliveries={change.deliveries ?? []}
                onChange={(deliveries) =>
                  updateChange(change.clientId, { deliveries })
                }
              />
              <button
                type="button"
                className="self-start text-xs text-muted-foreground underline"
                onClick={() => setShowUpload((value) => !value)}
              >
                {showUpload ? 'Hide Excel upload' : 'Or upload an Excel sheet'}
              </button>
              {showUpload && (
                <DeliveryUploadPanel
                  onConfirm={(deliveries) => {
                    updateChange(change.clientId, {
                      deliveries: [...(change.deliveries ?? []), ...deliveries],
                    })
                    setShowUpload(false)
                  }}
                />
              )}
            </div>
          )}

          {change.kind === 'add_deliveries' && !depot && (
            <div className="text-sm text-muted-foreground">
              Loading depot map…
            </div>
          )}

          {change.kind === 'driver_count_change' && (
            <div className="grid gap-3 md:grid-cols-2">
              <label className="flex flex-col gap-1.5 text-sm">
                <span className="font-medium">Driver count change</span>
                <input
                  type="number"
                  step={1}
                  value={change.driver_delta ?? 0}
                  onChange={(event) =>
                    updateChange(change.clientId, {
                      driver_delta: Number.parseInt(event.target.value, 10) || 0,
                    })
                  }
                  className="rounded-md border border-border bg-background px-3 py-2"
                />
              </label>
              <label className="flex flex-col gap-1.5 text-sm">
                <span className="font-medium">Allow overtime</span>
                <select
                  value={String(change.allow_overtime ?? true)}
                  onChange={(event) =>
                    updateChange(change.clientId, {
                      allow_overtime: event.target.value === 'true',
                    })
                  }
                  className="rounded-md border border-border bg-background px-3 py-2"
                >
                  <option value="true">Yes</option>
                  <option value="false">No</option>
                </select>
              </label>
            </div>
          )}

          {change.kind === 'delivery_frequency_day_change' && (
            <div className="grid gap-3 md:grid-cols-2">
              <label className="flex flex-col gap-1.5 text-sm">
                <span className="font-medium">Target day</span>
                <select
                  value={change.target_day ?? 'Thursday'}
                  onChange={(event) =>
                    updateChange(change.clientId, { target_day: event.target.value })
                  }
                  className="rounded-md border border-border bg-background px-3 py-2"
                >
                  <option value="Wednesday">Wednesday</option>
                  <option value="Thursday">Thursday</option>
                  <option value="Friday">Friday</option>
                </select>
              </label>
              <label className="flex flex-col gap-1.5 text-sm">
                <span className="font-medium">Target segment</span>
                <select
                  value={change.target_customers ?? 'flexible_independents'}
                  onChange={(event) =>
                    updateChange(change.clientId, {
                      target_customers: event.target.value,
                    })
                  }
                  className="rounded-md border border-border bg-background px-3 py-2"
                >
                  <option value="flexible_independents">
                    Flexible independent retailers
                  </option>
                  <option value="low_volume">Low-volume customers</option>
                  <option value="non_strategic">Non-strategic accounts</option>
                </select>
              </label>
            </div>
          )}

          {change.kind === 'facility_move' && (
            <div className="grid gap-3 md:grid-cols-2">
              <label className="flex flex-col gap-1.5 text-sm">
                <span className="font-medium">New depot lat</span>
                <input
                  type="number"
                  step={0.0001}
                  value={change.new_depot_location?.lat ?? depotLocation.lat}
                  onChange={(event) =>
                    updateChange(change.clientId, {
                      new_depot_location: {
                        lat: Number.parseFloat(event.target.value),
                        lng: change.new_depot_location?.lng ?? depotLocation.lng,
                      },
                    })
                  }
                  className="rounded-md border border-border bg-background px-3 py-2"
                />
              </label>
              <label className="flex flex-col gap-1.5 text-sm">
                <span className="font-medium">New depot lng</span>
                <input
                  type="number"
                  step={0.0001}
                  value={change.new_depot_location?.lng ?? depotLocation.lng}
                  onChange={(event) =>
                    updateChange(change.clientId, {
                      new_depot_location: {
                        lat: change.new_depot_location?.lat ?? depotLocation.lat,
                        lng: Number.parseFloat(event.target.value),
                      },
                    })
                  }
                  className="rounded-md border border-border bg-background px-3 py-2"
                />
              </label>
            </div>
          )}
        </div>
      ))}

      {costOverrideEnabled && (
        <CostParameterForm
          value={costOverride}
          onChange={onCostChange}
          onRemove={() => onCostEnabledChange(false)}
        />
      )}
    </div>
  )
}
