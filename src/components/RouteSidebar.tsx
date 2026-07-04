import { Clock, Package, Route as RouteIcon, Truck } from 'lucide-react'
import type { Route } from '@/api/types'
import { formatMinutes, formatNumber } from '@/lib/format'
import { routeColorCss } from '@/lib/routeColors'
import { cn } from '@/lib/utils'

interface RouteSidebarProps {
  routes: Route[]
  selectedRouteId: string | null
  onSelectRoute: (routeId: string | null) => void
  title?: string
}

export default function RouteSidebar({
  routes,
  selectedRouteId,
  onSelectRoute,
  title = 'Routes',
}: RouteSidebarProps) {
  const totals = routes.reduce(
    (acc, route) => {
      acc.stops += route.stops.length
      acc.cases += route.total_cases
      acc.miles += route.total_miles
      return acc
    },
    { stops: 0, cases: 0, miles: 0 },
  )

  return (
    <aside className="flex h-full w-[360px] flex-col border-r border-border bg-card/40 backdrop-blur">
      <div className="border-b border-border/70 px-4 py-3">
        <div className="text-[11px] uppercase tracking-wider text-muted-foreground">
          {title}
        </div>
        <div className="mt-2 grid grid-cols-3 gap-2 text-sm">
          <SidebarStat label="routes" value={routes.length} />
          <SidebarStat label="stops" value={totals.stops} />
          <SidebarStat label="cases" value={formatNumber(totals.cases)} />
        </div>
      </div>

      <div className="flex-1 overflow-y-auto">
        {routes.map((route, index) => {
          const isSelected = selectedRouteId === route.route_id
          const dimmed = selectedRouteId !== null && !isSelected
          return (
            <button
              key={route.route_id}
              onClick={() =>
                onSelectRoute(isSelected ? null : route.route_id)
              }
              className={cn(
                'w-full border-b border-border/40 px-4 py-3 text-left transition-colors',
                'hover:bg-accent/40',
                isSelected && 'bg-accent/60',
                dimmed && 'opacity-50',
              )}
            >
              <div className="flex items-center gap-2">
                <span
                  className="h-2.5 w-2.5 rounded-full"
                  style={{ backgroundColor: routeColorCss(index) }}
                />
                <RouteIcon className="h-3.5 w-3.5 text-muted-foreground" />
                <span className="text-sm font-semibold">{route.route_name}</span>
                <span className="ml-auto text-[11px] text-muted-foreground tabular-nums">
                  {route.driver_name}
                </span>
              </div>

              <div className="mt-2 grid grid-cols-4 gap-2 text-[11px] text-muted-foreground">
                <MiniMetric icon={Package} value={`${formatNumber(route.total_cases)} cases`} />
                <MiniMetric icon={Truck} value={`${formatNumber(route.total_miles, 1)} mi`} />
                <MiniMetric icon={Clock} value={formatMinutes(route.drive_minutes + route.service_minutes)} />
                <MiniMetric icon={Clock} value={`${route.overtime_minutes} OT`} />
              </div>

              <ol className="mt-3 space-y-1.5">
                {route.stops.map((stop) => (
                  <li
                    key={stop.stop_id}
                    className="flex items-start gap-2 text-[11px]"
                  >
                    <div className="mt-0.5 flex h-4 w-4 flex-shrink-0 items-center justify-center rounded-full bg-secondary text-[9px] font-medium text-muted-foreground">
                      {stop.sequence}
                    </div>
                    <div className="min-w-0 flex-1">
                      <div className="truncate font-medium text-foreground/90">
                        {stop.customer_name}
                      </div>
                      <div className="truncate text-muted-foreground">
                        {stop.demand_cases} cases · {stop.delivery_day}
                      </div>
                    </div>
                    <div className="flex-shrink-0 text-right text-muted-foreground tabular-nums">
                      {stop.arrival_time}
                    </div>
                  </li>
                ))}
              </ol>
            </button>
          )
        })}
      </div>
    </aside>
  )
}

function SidebarStat({ label, value }: { label: string; value: string | number }) {
  return (
    <div className="rounded-md border border-border/60 bg-background/40 p-2">
      <div className="text-base font-semibold tabular-nums">{value}</div>
      <div className="text-[10px] uppercase tracking-wider text-muted-foreground">
        {label}
      </div>
    </div>
  )
}

function MiniMetric({
  icon: Icon,
  value,
}: {
  icon: typeof Clock
  value: string
}) {
  return (
    <div className="flex items-center gap-1">
      <Icon className="h-3 w-3" />
      <span className="truncate">{value}</span>
    </div>
  )
}
