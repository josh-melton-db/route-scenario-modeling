import { useMemo, useState } from 'react'
import DeckGL from '@deck.gl/react'
import { IconLayer, PathLayer, ScatterplotLayer } from '@deck.gl/layers'
import { Map as MapLibreMap } from 'react-map-gl/maplibre'
import 'maplibre-gl/dist/maplibre-gl.css'
import type { DeliveryDraft, Depot, Route, Stop } from '@/api/types'
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

interface DraftStopDatum extends DeliveryDraft {
  draft_id: string
}

interface MapViewProps {
  depot: Depot
  routes: Route[]
  selectedRouteId: string | null
  onSelectRoute: (routeId: string | null) => void
  viewState?: ViewState
  onViewStateChange?: (viewState: ViewState) => void
  editable?: boolean
  draftStops?: DeliveryDraft[]
  selectedDraftIndex?: number | null
  onMapClick?: (lngLat: { lat: number; lng: number }) => void
  onSelectDraftStop?: (index: number | null) => void
}

function initialView(depot: Depot, routes: Route[], draftStops: DeliveryDraft[]): ViewState {
  const points = [
    depot.location,
    ...routes.flatMap((route) => route.stops.map((stop) => stop.location)),
    ...draftStops.map((stop) => ({ lat: stop.lat, lng: stop.lng })),
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
  editable = false,
  draftStops = [],
  selectedDraftIndex = null,
  onMapClick,
  onSelectDraftStop,
}: MapViewProps) {
  const fallbackInitialView = useMemo(
    () => initialView(depot, routes, draftStops),
    [depot, draftStops, routes],
  )
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

  const draftData = useMemo<DraftStopDatum[]>(
    () =>
      draftStops.map((stop, index) => ({
        ...stop,
        draft_id: `draft-${index}`,
      })),
    [draftStops],
  )

  const layers = useMemo(() => {
    const isSelected = (routeId: string) =>
      selectedRouteId === null || selectedRouteId === routeId

    const baseLayers = [
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
        pickable: !editable,
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
        pickable: !editable,
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

    if (!editable) return baseLayers

    return [
      ...baseLayers,
      new ScatterplotLayer<DraftStopDatum>({
        id: 'draft-stops',
        data: draftData,
        getPosition: (datum) => [datum.lng, datum.lat],
        getFillColor: (_datum, context) =>
          context.index === selectedDraftIndex
            ? [250, 204, 21, 255]
            : [52, 211, 153, 240],
        getLineColor: [15, 23, 42, 255],
        stroked: true,
        lineWidthMinPixels: 2,
        radiusUnits: 'pixels',
        getRadius: (_datum, context) =>
          context.index === selectedDraftIndex ? 12 : 9,
        pickable: true,
        updateTriggers: {
          getFillColor: [selectedDraftIndex],
          getRadius: [selectedDraftIndex],
        },
      }),
    ]
  }, [depot, draftData, editable, paths, selectedDraftIndex, selectedRouteId, stops])

  return (
    <div className="relative h-full w-full overflow-hidden rounded-lg border border-border bg-card">
      {editable && (
        <div className="pointer-events-none absolute left-3 top-3 z-10 rounded-md border border-border/70 bg-background/80 px-2 py-1 text-[11px] text-muted-foreground backdrop-blur">
          Click the map to drop a delivery pin
        </div>
      )}
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
        onClick={(info) => {
          if (editable) {
            if (info.object && 'draft_id' in info.object) {
              const draftId = String((info.object as DraftStopDatum).draft_id)
              const index = Number(draftId.replace('draft-', ''))
              onSelectDraftStop?.(Number.isFinite(index) ? index : null)
              return
            }
            if (info.coordinate) {
              onMapClick?.({
                lng: Number(info.coordinate[0]),
                lat: Number(info.coordinate[1]),
              })
              onSelectDraftStop?.(null)
            }
            return
          }
          if (!info.object) {
            onSelectRoute(null)
            return
          }
          if ('route_id' in info.object) {
            onSelectRoute((info.object as { route_id: string }).route_id)
          }
        }}
        getTooltip={({ object }) => {
          if (!object) return null
          if ('draft_id' in object) {
            const draft = object as DraftStopDatum
            return {
              html: `<div class="deck-tooltip">
                <div style="font-weight:600">${draft.customer_name}</div>
                <div style="font-size:11px;opacity:0.8">${draft.demand_cases} cases · ${draft.lat.toFixed(4)}, ${draft.lng.toFixed(4)}</div>
              </div>`,
              style: { backgroundColor: 'transparent', padding: '0' },
            }
          }
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
