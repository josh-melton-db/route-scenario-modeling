import { useMemo, useState } from 'react'
import DeckGL from '@deck.gl/react'
import { IconLayer, PathLayer, ScatterplotLayer } from '@deck.gl/layers'
import { Map as MapLibreMap } from 'react-map-gl/maplibre'
import 'maplibre-gl/dist/maplibre-gl.css'
import type { Depot, Route, Stop } from '@/api/types'
import { routeColor } from '@/lib/routeColors'

interface ViewState {
  longitude: number
  latitude: number
  zoom: number
  bearing: number
  pitch: number
}

interface PathDatum {
  route_id: string
  route_name: string
  path: [number, number][]
  color: [number, number, number]
}

interface StopDatum extends Stop {
  route_id: string
  route_name: string
  color: [number, number, number]
}

interface MapViewProps {
  depot: Depot
  routes: Route[]
  selectedRouteId: string | null
  onSelectRoute: (routeId: string | null) => void
  viewState?: ViewState
  onViewStateChange?: (viewState: ViewState) => void
}

function initialView(depot: Depot, routes: Route[]): ViewState {
  const points = [
    depot.location,
    ...routes.flatMap((route) => route.stops.map((stop) => stop.location)),
  ]
  const minLat = Math.min(...points.map((point) => point.lat))
  const maxLat = Math.max(...points.map((point) => point.lat))
  const minLng = Math.min(...points.map((point) => point.lng))
  const maxLng = Math.max(...points.map((point) => point.lng))
  return {
    longitude: (minLng + maxLng) / 2,
    latitude: (minLat + maxLat) / 2,
    zoom: 7.2,
    bearing: 0,
    pitch: 30,
  }
}

export default function MapView({
  depot,
  routes,
  selectedRouteId,
  onSelectRoute,
  viewState,
  onViewStateChange,
}: MapViewProps) {
  const fallbackInitialView = useMemo(() => initialView(depot, routes), [depot, routes])
  const [localViewState, setLocalViewState] = useState<ViewState>(fallbackInitialView)
  const activeViewState = viewState ?? localViewState

  const paths = useMemo<PathDatum[]>(
    () =>
      routes.map((route, index) => ({
        route_id: route.route_id,
        route_name: route.route_name,
        path: route.path.map((point) => [point.lng, point.lat] as [number, number]),
        color: routeColor(index),
      })),
    [routes],
  )

  const stops = useMemo<StopDatum[]>(
    () =>
      routes.flatMap((route, index) =>
        route.stops.map((stop) => ({
          ...stop,
          route_id: route.route_id,
          route_name: route.route_name,
          color: routeColor(index),
        })),
      ),
    [routes],
  )

  const layers = useMemo(() => {
    const isSelected = (routeId: string) =>
      selectedRouteId === null || selectedRouteId === routeId

    return [
      new PathLayer<PathDatum>({
        id: 'route-paths',
        data: paths,
        getPath: (datum) => datum.path,
        getColor: (datum) =>
          isSelected(datum.route_id)
            ? [...datum.color, 230]
            : [...datum.color, 60],
        widthMinPixels: 3,
        widthMaxPixels: 7,
        getWidth: (datum) => (isSelected(datum.route_id) ? 5 : 3),
        capRounded: true,
        jointRounded: true,
        pickable: true,
        updateTriggers: {
          getColor: [selectedRouteId],
          getWidth: [selectedRouteId],
        },
      }),
      new ScatterplotLayer<StopDatum>({
        id: 'stops',
        data: stops,
        getPosition: (datum) => [datum.location.lng, datum.location.lat],
        getFillColor: (datum) =>
          isSelected(datum.route_id)
            ? [...datum.color, datum.is_new_customer ? 255 : 230]
            : [...datum.color, 80],
        getLineColor: (datum) =>
          datum.window_risk === 'missed'
            ? [248, 113, 113, 255]
            : [255, 255, 255, 180],
        stroked: true,
        lineWidthMinPixels: 1.5,
        radiusUnits: 'pixels',
        getRadius: (datum) =>
          datum.is_new_customer ? 10 : isSelected(datum.route_id) ? 8 : 5,
        pickable: true,
        updateTriggers: {
          getFillColor: [selectedRouteId],
          getRadius: [selectedRouteId],
        },
      }),
      new IconLayer<Depot>({
        id: 'depot',
        data: [depot],
        getPosition: (datum) => [datum.location.lng, datum.location.lat],
        getIcon: () => ({
          url:
            'data:image/svg+xml;utf8,' +
            encodeURIComponent(
              `<svg xmlns="http://www.w3.org/2000/svg" width="48" height="48" viewBox="0 0 24 24" fill="none" stroke="white" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><circle cx="12" cy="12" r="10" fill="hsl(188 95% 48%)"/><path d="M3 21h18"/><path d="M6 21V9l6-4 6 4v12"/><path d="M9 21v-6h6v6"/></svg>`,
            ),
          width: 48,
          height: 48,
          anchorY: 24,
        }),
        sizeUnits: 'pixels',
        getSize: 30,
        pickable: true,
      }),
    ]
  }, [depot, paths, selectedRouteId, stops])

  return (
    <div className="relative h-full w-full overflow-hidden rounded-lg border border-border bg-card">
      <DeckGL
        viewState={activeViewState}
        onViewStateChange={({ viewState: next }) => {
          if (
            next &&
            typeof next === 'object' &&
            'longitude' in next &&
            'latitude' in next &&
            'zoom' in next
          ) {
            const normalized = {
              longitude: Number(next.longitude),
              latitude: Number(next.latitude),
              zoom: Number(next.zoom),
              bearing: Number(next.bearing ?? 0),
              pitch: Number(next.pitch ?? 0),
            }
            setLocalViewState(normalized)
            onViewStateChange?.(normalized)
          }
        }}
        controller
        layers={layers}
        onClick={({ object }) => {
          if (!object) {
            onSelectRoute(null)
            return
          }
          if ('route_id' in object) {
            onSelectRoute((object as { route_id: string }).route_id)
          }
        }}
        getTooltip={({ object }) => {
          if (!object) return null
          if ('customer_name' in object) {
            const stop = object as StopDatum
            return {
              html: `<div class="deck-tooltip">
                <div style="font-weight:600">${stop.customer_name}</div>
                <div style="font-size:11px;opacity:0.8">${stop.route_name} · stop ${stop.sequence}</div>
                <div style="font-size:11px;margin-top:4px">${stop.demand_cases} cases · ${stop.arrival_time}</div>
              </div>`,
              style: { backgroundColor: 'transparent', padding: '0' },
            }
          }
          if ('route_name' in object && 'path' in object) {
            const route = object as PathDatum
            return {
              html: `<div class="deck-tooltip"><strong>${route.route_name}</strong></div>`,
              style: { backgroundColor: 'transparent', padding: '0' },
            }
          }
          if ('name' in object) {
            const mappedDepot = object as Depot
            return {
              html: `<div class="deck-tooltip"><strong>${mappedDepot.name}</strong><div style="font-size:11px;opacity:0.8">Depot</div></div>`,
              style: { backgroundColor: 'transparent', padding: '0' },
            }
          }
          return null
        }}
      >
        <MapLibreMap
          reuseMaps
          mapStyle="https://basemaps.cartocdn.com/gl/dark-matter-gl-style/style.json"
        />
      </DeckGL>
    </div>
  )
}

export type { ViewState }
