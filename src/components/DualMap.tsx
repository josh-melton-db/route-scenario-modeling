import { useState } from 'react'
import type { ReactNode } from 'react'
import type { Depot, Route, RunStatus } from '@/api/types'
import MapView, { type ViewState } from './MapView'

interface DualMapProps {
  baselineDepot: Depot
  scenarioDepot: Depot
  baselineRoutes: Route[]
  scenarioRoutes: Route[]
  status: RunStatus
}

export default function DualMap({
  baselineDepot,
  scenarioDepot,
  baselineRoutes,
  scenarioRoutes,
  status,
}: DualMapProps) {
  const [selectedRouteId, setSelectedRouteId] = useState<string | null>(null)
  const [viewState, setViewState] = useState<ViewState | undefined>()

  return (
    <div className="grid min-h-[520px] grid-cols-1 gap-4 lg:grid-cols-2">
      <MapPanel title="Baseline">
        <MapView
          depot={baselineDepot}
          routes={baselineRoutes}
          selectedRouteId={selectedRouteId}
          onSelectRoute={setSelectedRouteId}
          viewState={viewState}
          onViewStateChange={setViewState}
        />
      </MapPanel>
      <MapPanel title={status === 'infeasible' ? 'Scenario (infeasible)' : 'Scenario'}>
        <MapView
          depot={scenarioDepot}
          routes={scenarioRoutes}
          selectedRouteId={selectedRouteId}
          onSelectRoute={setSelectedRouteId}
          viewState={viewState}
          onViewStateChange={setViewState}
        />
      </MapPanel>
    </div>
  )
}

function MapPanel({
  title,
  children,
}: {
  title: string
  children: ReactNode
}) {
  return (
    <div className="flex min-h-[520px] flex-col gap-2">
      <div className="text-sm font-semibold">{title}</div>
      <div className="min-h-0 flex-1">{children}</div>
    </div>
  )
}
