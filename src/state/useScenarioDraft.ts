import { create } from 'zustand'
import type {
  CostOverride,
  DraftScenarioChange,
  ValidationResponse,
  OperatingConstraints,
  TransportationChoices,
} from '@/api/types'

export interface ScenarioDraftState {
  scenario_name: string
  depot_id: string
  delivery_day: string
  changes: DraftScenarioChange[]
  costOverride: CostOverride
  costOverrideEnabled: boolean
  operatingConstraints: OperatingConstraints
  transportationChoices: TransportationChoices
  validation: ValidationResponse | null
  setScenarioName: (scenarioName: string) => void
  setDepotDay: (depotId: string, deliveryDay: string) => void
  setChanges: (changes: DraftScenarioChange[]) => void
  setCostOverride: (costOverride: CostOverride) => void
  setCostOverrideEnabled: (enabled: boolean) => void
  setOperatingConstraints: (value: OperatingConstraints) => void
  setTransportationChoices: (value: TransportationChoices) => void
  setValidation: (validation: ValidationResponse | null) => void
  buildParameters: () => Record<string, unknown>
  reset: () => void
}

const initialState = {
  scenario_name: 'Custom scenario',
  depot_id: 'DPT_NORTH',
  delivery_day: 'Tuesday',
  changes: [] as DraftScenarioChange[],
  costOverride: {} as CostOverride,
  costOverrideEnabled: false,
  validation: null as ValidationResponse | null,
  operatingConstraints: {
    private_vehicle_limit: 4,
    max_route_minutes: 600,
    max_stops_per_route: 8,
    allow_overtime: true,
  },
  transportationChoices: {
    allow_private_fleet: true,
    allow_carrier: false,
    carrier_name: 'Great Lakes Logistics',
    contract_name: 'GL-Standard-2026',
    carrier_capacity_stops: 12,
    rate_per_mile: 4.25,
    rate_per_stop: 45,
    minimum_charge: 350,
    fuel_surcharge_pct: 12,
  },
}

function hasCostValues(cost: CostOverride): boolean {
  return Object.values(cost).some((value) => value !== null && value !== undefined)
}

function uniqueChanges(changes: DraftScenarioChange[]): DraftScenarioChange[] {
  const activeKinds = new Set<string>()
  return changes.filter((change) => {
    if (activeKinds.has(change.kind)) return false
    activeKinds.add(change.kind)
    return true
  })
}

export const useScenarioDraft = create<ScenarioDraftState>((set, get) => ({
  ...initialState,
  setScenarioName: (scenario_name) => set({ scenario_name }),
  setDepotDay: (depot_id, delivery_day) =>
    set({ depot_id, delivery_day, validation: null }),
  setChanges: (changes) =>
    set({ changes: uniqueChanges(changes), validation: null }),
  setCostOverride: (costOverride) =>
    set({ costOverride, costOverrideEnabled: true, validation: null }),
  setCostOverrideEnabled: (costOverrideEnabled) =>
    set((state) => ({
      costOverrideEnabled,
      costOverride: costOverrideEnabled ? state.costOverride : {},
      validation: null,
    })),
  setOperatingConstraints: (operatingConstraints) =>
    set({ operatingConstraints, validation: null }),
  setTransportationChoices: (transportationChoices) =>
    set({ transportationChoices, validation: null }),
  setValidation: (validation) => set({ validation }),
  buildParameters: () => {
    const state = get()
    const parameters: Record<string, unknown> = {
      changes: state.changes.map(({ clientId: _clientId, ...change }) => change),
      operating_constraints: state.operatingConstraints,
      transportation_choices: state.transportationChoices,
    }
    if (state.costOverrideEnabled && hasCostValues(state.costOverride)) {
      parameters.cost = state.costOverride
    }
    return parameters
  },
  reset: () => set(initialState),
}))
