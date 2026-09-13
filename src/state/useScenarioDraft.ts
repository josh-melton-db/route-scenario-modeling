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
  operatingConstraintsEnabled: boolean
  transportationChoicesEnabled: boolean
  validation: ValidationResponse | null
  setScenarioName: (scenarioName: string) => void
  setDepotDay: (depotId: string, deliveryDay: string) => void
  setChanges: (changes: DraftScenarioChange[]) => void
  setCostOverride: (costOverride: CostOverride) => void
  setCostOverrideEnabled: (enabled: boolean) => void
  setOperatingConstraints: (value: OperatingConstraints) => void
  setTransportationChoices: (value: TransportationChoices) => void
  setOperatingConstraintsEnabled: (enabled: boolean) => void
  setTransportationChoicesEnabled: (enabled: boolean) => void
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
    parameter_set_id: 'default',
    private_vehicle_limit: 4,
    max_route_minutes: 600,
    max_stops_per_route: 8,
    allow_overtime: true,
  },
  transportationChoices: {
    allow_private_fleet: true,
    allow_carrier: false,
    carrier_id: 'GL_LOGISTICS',
    contract_id: 'GL_STANDARD_2026',
  },
  operatingConstraintsEnabled: false,
  transportationChoicesEnabled: false,
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
  setOperatingConstraintsEnabled: (operatingConstraintsEnabled) =>
    set({ operatingConstraintsEnabled, validation: null }),
  setTransportationChoicesEnabled: (transportationChoicesEnabled) =>
    set({ transportationChoicesEnabled, validation: null }),
  setValidation: (validation) => set({ validation }),
  buildParameters: () => {
    const state = get()
    const parameters: Record<string, unknown> = {
      changes: state.changes.map(({ clientId: _clientId, ...change }) => change),
    }
    if (state.operatingConstraintsEnabled) parameters.operating_constraints = state.operatingConstraints
    if (state.transportationChoicesEnabled) parameters.transportation_choices = state.transportationChoices
    if (state.costOverrideEnabled && hasCostValues(state.costOverride)) {
      parameters.cost = state.costOverride
    }
    return parameters
  },
  reset: () => set(initialState),
}))
