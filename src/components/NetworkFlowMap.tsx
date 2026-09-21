import { useEffect, useMemo, useState } from 'react'
import DeckGL from '@deck.gl/react'
import { ArcLayer, PathLayer, ScatterplotLayer } from '@deck.gl/layers'
import { Map as MapLibreMap } from 'react-map-gl/maplibre'
import 'maplibre-gl/dist/maplibre-gl.css'
import type {
  NetworkFacilityAggregate,
  NetworkLaneAggregate,
} from '@/api/types'
import { formatCurrency, formatNumber, formatPercent } from '@/lib/format'

type Rgba = [number, number, number, number]

interface ViewState {
  longitude: number
  latitude: number
  zoom: number
  bearing: number
  pitch: number
}

interface NetworkFlowMapProps {
  facilities: NetworkFacilityAggregate[]
  lanes: NetworkLaneAggregate[]
  selectedFacilityId: string | null
  selectedLaneId: string | null
  onSelectFacility: (facilityId: string | null) => void
  onSelectLane: (laneId: string | null) => void
}

export default function NetworkFlowMap({
  facilities,
  lanes,
  selectedFacilityId,
  selectedLaneId,
  onSelectFacility,
  onSelectLane,
}: NetworkFlowMapProps) {
  const calculatedView = useMemo(() => fitView(facilities, lanes), [facilities, lanes])
  const [viewState, setViewState] = useState<ViewState>(calculatedView)
  const colors = useMemo(
    () => ({
      primary: tokenColor('--primary', 230),
      foreground: tokenColor('--foreground', 230),
      muted: tokenColor('--muted-foreground', 150),
      success: tokenColor('--success', 220),
      warning: tokenColor('--warning', 230),
      destructive: tokenColor('--destructive', 235),
    }),
    [],
  )

  useEffect(() => {
    setViewState(calculatedView)
  }, [calculatedView])

  const unmetByFacility = useMemo(() => {
    const ratios = new Map<string, number>()
    for (const facility of facilities) {
      ratios.set(
        facility.facility_id,
        facility.demand_units > 0
          ? Math.max(0, facility.demand_units - facility.assigned_units) /
            facility.demand_units
          : 0,
      )
    }
    return ratios
  }, [facilities])
  const unmetCasesByFacility = useMemo(() => {
    const cases = new Map<string, number>()
    for (const facility of facilities) {
      cases.set(
        facility.facility_id,
        Math.max(0, facility.demand_units - facility.assigned_units),
      )
    }
    return cases
  }, [facilities])
  const maxFlow = useMemo(
    () => Math.max(1, ...lanes.map((lane) => lane.assigned_units)),
    [lanes],
  )
  const maxFacilityFlow = useMemo(
    () => Math.max(1, ...facilities.map((facility) => facility.assigned_units)),
    [facilities],
  )

  const layers = useMemo(
    () => {
      const unmetColor = (lane: NetworkLaneAggregate): Rgba => {
        if (lane.lane_id === selectedLaneId) return colors.foreground
        const ratio = laneUnmetRatio(lane, unmetByFacility)
        if (ratio >= 0.1) return colors.destructive
        if (ratio > 0.01) return colors.warning
        return colors.success
      }
      const arcWidth = (lane: NetworkLaneAggregate) => {
        const base = 2 + Math.sqrt(lane.assigned_units / maxFlow) * 8
        return lane.lane_id === selectedLaneId ? base + 3 : base
      }
      const localWidth = (lane: NetworkLaneAggregate) => {
        const base = 1 + Math.sqrt(lane.assigned_units / maxFlow) * 5
        return lane.lane_id === selectedLaneId ? base + 2 : base
      }
      const linehaul = lanes.filter((lane) => lane.lane_type === 'LINEHAUL')
      const local = lanes.filter((lane) => lane.lane_type !== 'LINEHAUL')
      return [
        new ArcLayer<NetworkLaneAggregate>({
          id: 'network-linehaul-arcs',
          data: linehaul,
          getSourcePosition: (lane) => [
            lane.origin_location.lng,
            lane.origin_location.lat,
          ],
          getTargetPosition: (lane) => [
            lane.destination_location.lng,
            lane.destination_location.lat,
          ],
          getSourceColor: unmetColor,
          getTargetColor: (lane) => {
            if (lane.lane_id === selectedLaneId) return colors.foreground
            const color = unmetColor(lane)
            return [color[0], color[1], color[2], Math.min(color[3], 120)]
          },
          getWidth: arcWidth,
          getHeight: (lane) =>
            0.3 + Math.min(1, lane.assigned_units / maxFlow) * 0.3,
          getTilt: 20,
          widthUnits: 'pixels',
          widthMinPixels: 2,
          widthMaxPixels: 13,
          pickable: true,
          autoHighlight: true,
          greatCircle: false,
          updateTriggers: {
            getSourceColor: [selectedLaneId, unmetByFacility, colors],
            getTargetColor: [selectedLaneId, unmetByFacility, colors],
            getWidth: [maxFlow, selectedLaneId],
            getHeight: [maxFlow],
          },
        }),
        new PathLayer<NetworkLaneAggregate>({
          id: 'network-local-lanes',
          data: local,
          getPath: (lane) => [
            [lane.origin_location.lng, lane.origin_location.lat],
            [lane.destination_location.lng, lane.destination_location.lat],
          ],
          getColor: unmetColor,
          getWidth: localWidth,
          widthUnits: 'pixels',
          widthMinPixels: 1,
          widthMaxPixels: 7,
          capRounded: true,
          jointRounded: true,
          pickable: true,
          autoHighlight: true,
          updateTriggers: {
            getColor: [selectedLaneId, unmetByFacility, colors],
            getWidth: [maxFlow, selectedLaneId],
          },
        }),
        new ScatterplotLayer<NetworkFacilityAggregate>({
          id: 'network-facilities',
          data: facilities,
          getPosition: (facility) => [facility.location.lng, facility.location.lat],
          getRadius: (facility) =>
            7 + Math.sqrt(facility.assigned_units / maxFacilityFlow) * 13,
          radiusUnits: 'pixels',
          getFillColor: (facility) =>
            facility.facility_type === 'distribution_center'
              ? colors.primary
              : colors.success,
          getLineColor: (facility) =>
            facility.facility_id === selectedFacilityId
              ? colors.foreground
              : [255, 255, 255, 160],
          getLineWidth: (facility) =>
            facility.facility_id === selectedFacilityId ? 4 : 2,
          lineWidthUnits: 'pixels',
          stroked: true,
          pickable: true,
          autoHighlight: true,
          updateTriggers: {
            getRadius: [maxFacilityFlow],
            getLineColor: [selectedFacilityId],
            getLineWidth: [selectedFacilityId],
          },
        }),
      ]
    },
    [
      colors,
      facilities,
      lanes,
      maxFacilityFlow,
      maxFlow,
      selectedFacilityId,
      selectedLaneId,
      unmetByFacility,
    ],
  )

  return (
    <div className="relative h-[620px] min-h-0 overflow-hidden rounded-lg border border-border bg-card">
      <DeckGL
        viewState={viewState}
        controller
        layers={layers}
        onViewStateChange={({ viewState: next }) => {
          if (next && 'longitude' in next && 'latitude' in next && 'zoom' in next) {
            setViewState({
              longitude: Number(next.longitude),
              latitude: Number(next.latitude),
              zoom: Number(next.zoom),
              bearing: Number(next.bearing ?? 0),
              pitch: Number(next.pitch ?? 0),
            })
          }
        }}
        onClick={({ object }) => {
          if (!object) {
            onSelectFacility(null)
            onSelectLane(null)
            return
          }
          if ('facility_id' in object) {
            onSelectFacility(String((object as NetworkFacilityAggregate).facility_id))
            onSelectLane(null)
            return
          }
          if ('lane_id' in object) {
            onSelectLane(String((object as NetworkLaneAggregate).lane_id))
            onSelectFacility(null)
          }
        }}
        getTooltip={({ object }) => {
          if (!object) return null
          if ('facility_id' in object) {
            const facility = object as NetworkFacilityAggregate
            const unmet = unmetCasesByFacility.get(facility.facility_id) ?? 0
            return tooltip(`
              <strong>${escapeHtml(facility.facility_name)}</strong>
              <div>${facility.facility_type === 'distribution_center' ? 'Distribution center' : 'Depot'}</div>
              <div style="margin-top:4px">${formatNumber(facility.assigned_units)} assigned · ${formatPercent(facility.utilization_pct)} utilized</div>
              <div>${unmet > 0 ? `${formatNumber(unmet)} unmet` : 'No unmet demand'}</div>
            `)
          }
          const lane = object as NetworkLaneAggregate
          const laneUnmet = laneUnmetCases(lane, unmetCasesByFacility)
          return tooltip(`
            <strong>${escapeHtml(lane.lane_name)}</strong>
            <div>${escapeHtml(lane.origin_endpoint_name)} → ${escapeHtml(lane.destination_endpoint_name)}</div>
            <div style="margin-top:4px">${formatNumber(lane.assigned_units)} cases · ${formatPercent(lane.utilization_pct)}</div>
            <div>${formatCurrency(lane.total_cost)} modeled cost</div>
            <div>${laneUnmet > 0 ? `${formatNumber(laneUnmet)} unmet at destination` : 'Destination demand served'}</div>
          `)
        }}
      >
        <MapLibreMap
          reuseMaps
          mapStyle="https://basemaps.cartocdn.com/gl/dark-matter-gl-style/style.json"
        />
      </DeckGL>

      <div className="pointer-events-none absolute bottom-3 left-3 rounded-md border border-border bg-background/90 p-3 text-[11px] shadow-lg backdrop-blur">
        <div className="font-medium">Unmet demand by lane</div>
        <div className="mt-2 flex items-center gap-3 text-muted-foreground">
          <span className="flex items-center gap-1.5">
            <span className="h-1.5 w-4 rounded bg-success" /> Served
          </span>
          <span className="flex items-center gap-1.5">
            <span className="h-1.5 w-4 rounded bg-warning" /> 1–10%
          </span>
          <span className="flex items-center gap-1.5">
            <span className="h-1.5 w-4 rounded bg-destructive" /> &gt;10%
          </span>
        </div>
        <div className="mt-2 flex flex-col gap-1 border-t border-border pt-2 text-muted-foreground">
          <span className="flex items-center gap-1.5">
            <svg width="18" height="10" viewBox="0 0 18 10" aria-hidden>
              <path d="M1 9 Q9 -3 17 9" fill="none" stroke="currentColor" strokeWidth="2" />
            </svg>
            Linehaul freight
          </span>
          <span className="flex items-center gap-1.5">
            <svg width="18" height="10" viewBox="0 0 18 10" aria-hidden>
              <line x1="1" y1="8" x2="17" y2="8" stroke="currentColor" strokeWidth="2" />
            </svg>
            Local distribution
          </span>
        </div>
        <div className="mt-2 flex items-center gap-2 border-t border-border pt-2 text-muted-foreground">
          <span className="h-1 w-3 rounded bg-muted-foreground" /> Thin
          <span className="h-2.5 w-6 rounded bg-muted-foreground" /> Thick = volume
        </div>
        <div className="mt-2 flex items-center gap-3 border-t border-border pt-2 text-muted-foreground">
          <span className="flex items-center gap-1.5">
            <span className="h-2.5 w-2.5 rounded-full border-2 border-white bg-primary" /> DC
          </span>
          <span className="flex items-center gap-1.5">
            <span className="h-2.5 w-2.5 rounded-full border-2 border-white bg-success" /> Depot
          </span>
        </div>
      </div>

      {lanes.length === 0 && (
        <div className="absolute inset-0 flex items-center justify-center bg-background/70 backdrop-blur-sm">
          <div className="rounded-md border border-border bg-card p-4 text-sm text-muted-foreground">
            No lanes match this planning context.
          </div>
        </div>
      )}
    </div>
  )
}

function laneUnmetRatio(
  lane: NetworkLaneAggregate,
  unmetByFacility: Map<string, number>,
): number {
  if (lane.destination_endpoint_type !== 'customer' && lane.destination_endpoint_type !== 'market') {
    const destination = unmetByFacility.get(lane.destination_endpoint_id)
    if (destination !== undefined) return destination
  }
  const origin = unmetByFacility.get(lane.origin_endpoint_id)
  return origin ?? 0
}

function laneUnmetCases(
  lane: NetworkLaneAggregate,
  unmetCasesByFacility: Map<string, number>,
): number {
  if (lane.destination_endpoint_type !== 'customer' && lane.destination_endpoint_type !== 'market') {
    const destination = unmetCasesByFacility.get(lane.destination_endpoint_id)
    if (destination !== undefined) return destination
  }
  return unmetCasesByFacility.get(lane.origin_endpoint_id) ?? 0
}

function fitView(
  facilities: NetworkFacilityAggregate[],
  lanes: NetworkLaneAggregate[],
): ViewState {
  const points = [
    ...facilities.map((row) => row.location),
    ...lanes.flatMap((row) => [row.origin_location, row.destination_location]),
  ]
  if (!points.length) {
    return { longitude: -88, latitude: 39, zoom: 4, bearing: 0, pitch: 0 }
  }
  const minLng = Math.min(...points.map((point) => point.lng))
  const maxLng = Math.max(...points.map((point) => point.lng))
  const minLat = Math.min(...points.map((point) => point.lat))
  const maxLat = Math.max(...points.map((point) => point.lat))
  const range = Math.max(maxLng - minLng, maxLat - minLat, 0.1)
  const zoom = Math.max(3, Math.min(8, 7.4 - Math.log2(range + 1)))
  return {
    longitude: (minLng + maxLng) / 2,
    latitude: (minLat + maxLat) / 2,
    zoom,
    bearing: 0,
    pitch: 20,
  }
}

function tokenColor(variable: string, alpha: number): Rgba {
  if (typeof window === 'undefined') return [255, 255, 255, alpha]
  const value = getComputedStyle(document.documentElement)
    .getPropertyValue(variable)
    .trim()
  const [rawHue, rawSaturation, rawLightness] = value.split(/\s+/)
  const hue = Number.parseFloat(rawHue)
  const saturation = Number.parseFloat(rawSaturation) / 100
  const lightness = Number.parseFloat(rawLightness) / 100
  if (![hue, saturation, lightness].every(Number.isFinite)) {
    return [255, 255, 255, alpha]
  }
  const chroma = (1 - Math.abs(2 * lightness - 1)) * saturation
  const section = ((hue % 360) + 360) % 360 / 60
  const x = chroma * (1 - Math.abs((section % 2) - 1))
  const channels =
    section < 1
      ? [chroma, x, 0]
      : section < 2
        ? [x, chroma, 0]
        : section < 3
          ? [0, chroma, x]
          : section < 4
            ? [0, x, chroma]
            : section < 5
              ? [x, 0, chroma]
              : [chroma, 0, x]
  const match = lightness - chroma / 2
  return [
    Math.round((channels[0] + match) * 255),
    Math.round((channels[1] + match) * 255),
    Math.round((channels[2] + match) * 255),
    alpha,
  ]
}

function tooltip(html: string) {
  return {
    html: `<div class="deck-tooltip">${html}</div>`,
    style: { backgroundColor: 'transparent', padding: '0' },
  }
}

function escapeHtml(value: string) {
  return value
    .replaceAll('&', '&amp;')
    .replaceAll('<', '&lt;')
    .replaceAll('>', '&gt;')
    .replaceAll('"', '&quot;')
    .replaceAll("'", '&#039;')
}
