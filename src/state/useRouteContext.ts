import { create } from 'zustand'
import type { ParentRouteContext } from '@/lib/networkLinks'

export type RouteFacilityType = 'distribution_center' | 'depot'

export interface RouteFacility {
  facilityId: string
  facilityName: string
  facilityType: RouteFacilityType
}

interface RouteContextState {
  facility: RouteFacility
  parent: ParentRouteContext
  setFacility: (facility: RouteFacility) => void
  setParent: (parent: ParentRouteContext) => void
}

const defaultFacility: RouteFacility = {
  facilityId: 'DPT_NORTH',
  facilityName: 'North Depot',
  facilityType: 'depot',
}

/**
 * The route optimizer is always scoped to one facility — either a distribution
 * center or one of its depots. Pages publish the facility they are showing here
 * so the nav keeps the same selection while moving between Depot, Scenarios,
 * Rates, and Inputs.
 */
export const useRouteContext = create<RouteContextState>((set) => ({
  facility: defaultFacility,
  parent: {},
  setFacility: (facility) =>
    set((state) =>
      state.facility.facilityId === facility.facilityId &&
      state.facility.facilityType === facility.facilityType &&
      state.facility.facilityName === facility.facilityName
        ? state
        : { facility },
    ),
  setParent: (parent) => set({ parent }),
}))
