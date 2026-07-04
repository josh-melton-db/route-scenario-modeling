import { useState } from 'react'
import { Loader2 } from 'lucide-react'
import CostBreakdown from '@/components/CostBreakdown'
import DepotDayFilter from '@/components/DepotDayFilter'
import ErrorState from '@/components/ErrorState'
import KpiDeltaGrid from '@/components/KpiDeltaGrid'
import MapView from '@/components/MapView'
import RouteSidebar from '@/components/RouteSidebar'
import {
  useBaselineKpis,
  useBaselineNetwork,
  useDays,
  useDepots,
} from '@/api/queries'

export default function BaselinePage() {
  const [depotId, setDepotId] = useState('DPT_NORTH')
  const [deliveryDay, setDeliveryDay] = useState('Tuesday')
  const [selectedRouteId, setSelectedRouteId] = useState<string | null>(null)

  const depots = useDepots()
  const days = useDays()
  const network = useBaselineNetwork(depotId, deliveryDay)
  const kpis = useBaselineKpis(depotId, deliveryDay)
  const error = depots.error ?? days.error ?? network.error ?? kpis.error

  if (error) return <ErrorState title="Could not load baseline" error={error} />

  const loading =
    depots.isLoading || days.isLoading || network.isLoading || kpis.isLoading

  return (
    <div className="flex flex-col gap-5 px-4 py-5 sm:px-6 lg:px-8">
      <header className="flex flex-wrap items-end justify-between gap-4">
        <div>
          <h1 className="text-2xl font-semibold tracking-tight">
            Baseline network
          </h1>
          <p className="mt-1 text-sm text-muted-foreground">
            Current-state Generic Co delivery routes and route-level operating metrics.
          </p>
        </div>
        <DepotDayFilter
          depots={depots.data ?? []}
          days={days.data ?? []}
          depotId={depotId}
          deliveryDay={deliveryDay}
          onChange={(nextDepot, nextDay) => {
            setDepotId(nextDepot)
            setDeliveryDay(nextDay)
            setSelectedRouteId(null)
          }}
        />
      </header>

      {loading || !network.data || !kpis.data ? (
        <div className="flex h-96 items-center justify-center text-muted-foreground">
          <Loader2 className="mr-2 h-4 w-4 animate-spin" />
          Loading baseline...
        </div>
      ) : (
        <>
          <KpiDeltaGrid baselineKpis={kpis.data} />
          <div className="grid gap-4 xl:grid-cols-[1fr_320px]">
            <div className="min-h-[620px]">
              <div className="flex h-[620px] min-h-0 overflow-hidden rounded-lg border border-border">
                <RouteSidebar
                  routes={network.data.routes}
                  selectedRouteId={selectedRouteId}
                  onSelectRoute={setSelectedRouteId}
                  title="Baseline routes"
                />
                <div className="min-w-0 flex-1 p-3">
                  <MapView
                    depot={network.data.depot}
                    routes={network.data.routes}
                    selectedRouteId={selectedRouteId}
                    onSelectRoute={setSelectedRouteId}
                  />
                </div>
              </div>
            </div>
            <CostBreakdown costs={kpis.data.cost_breakdown} />
          </div>
        </>
      )}
    </div>
  )
}
