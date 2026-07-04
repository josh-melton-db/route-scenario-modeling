import { create } from 'zustand'
import type { ScenarioType, ValidationResponse } from '@/api/types'

export interface ScenarioDraftState {
  scenario_type: ScenarioType | null
  scenario_name: string
  depot_id: string
  delivery_day: string
  parameters: Record<string, unknown>
  validation: ValidationResponse | null
  setScenarioType: (scenarioType: ScenarioType) => void
  setScenarioName: (scenarioName: string) => void
  setDepotDay: (depotId: string, deliveryDay: string) => void
  setParameter: (name: string, value: unknown) => void
  setParameters: (parameters: Record<string, unknown>) => void
  setValidation: (validation: ValidationResponse | null) => void
  reset: () => void
}

const initialState = {
  scenario_type: null,
  scenario_name: 'New scenario',
  depot_id: 'DPT_NORTH',
  delivery_day: 'Tuesday',
  parameters: {},
  validation: null,
}

export const useScenarioDraft = create<ScenarioDraftState>((set) => ({
  ...initialState,
  setScenarioType: (scenario_type) =>
    set({
      scenario_type,
      scenario_name:
        scenario_type === 'baseline'
          ? 'Baseline identity run'
          : 'New scenario',
      parameters: {},
      validation: null,
    }),
  setScenarioName: (scenario_name) => set({ scenario_name }),
  setDepotDay: (depot_id, delivery_day) => set({ depot_id, delivery_day }),
  setParameter: (name, value) =>
    set((state) => ({
      parameters: { ...state.parameters, [name]: value },
      validation: null,
    })),
  setParameters: (parameters) => set({ parameters, validation: null }),
  setValidation: (validation) => set({ validation }),
  reset: () => set(initialState),
}))
