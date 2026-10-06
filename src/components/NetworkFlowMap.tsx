import { useEffect, useMemo, useState } from 'react'
import DeckGL from '@deck.gl/react'
import { ArcLayer, PathLayer, ScatterplotLayer, TextLayer } from '@deck.gl/layers'
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
  const mapLanes = useMemo(
    () => lanes.filter((lane) => lane.lane_type === 'LINEHAUL' || lane.mode.toUpperCase() === 'AIR'),
    [lanes],
  )
  const calculatedView = useMemo(() => fitView(facilities, mapLanes), [facilities, mapLanes])
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

  const destinationDemand = useMemo(() => {
    const depotIds = new Set(facilities.filter((row) => row.facility_type === 'depot')
      .map((row) => row.facility_id))
    const inboundByDepot = new Map<string, number>()
    for (const lane of lanes) {
      if (lane.lane_type !== 'LINEHAUL' || !depotIds.has(lane.destination_endpoint_id)) continue
      inboundByDepot.set(lane.destination_endpoint_id,
        (inboundByDepot.get(lane.destination_endpoint_id) ?? 0) + lane.assigned_units)
    }
    const values = new Map<string, { demand: number; assigned: number }>()
    for (const facility of facilities) {
      const demandTargets = facility.facility_type === 'distribution_center'
        ? facilities.filter(
          (row) => row.facility_type === 'depot' && row.parent_facility_id === facility.facility_id,
        )
        : [facility]
      values.set(facility.facility_id, {
        demand: demandTargets.reduce((total, row) => total + row.demand_units, 0),
        // Market and delivery layers can repeat the same cases leaving a depot.
        // Incoming linehaul measures the supply actually available to its demand.
        assigned: demandTargets.reduce((total, row) =>
          total + (inboundByDepot.get(row.facility_id) ?? row.assigned_units), 0),
      })
    }
    return values
  }, [facilities, lanes])
  const unmetByFacility = useMemo(() => new Map(
    [...destinationDemand].map(([id, row]) => [id, row.demand > 0
      ? Math.max(0, row.demand - row.assigned) / row.demand : 0]),
  ), [destinationDemand])
  const unmetCasesByFacility = useMemo(() => new Map(
    [...destinationDemand].map(([id, row]) => [id, Math.max(0, row.demand - row.assigned)]),
  ), [destinationDemand])
  const maxFlow = useMemo(
    () => Math.max(1, ...mapLanes.map((lane) => Math.max(lane.capacity_units, lane.assigned_units))),
    [mapLanes],
  )
  const maxFacilityFlow = useMemo(
    () => Math.max(1, ...facilities.map((facility) => facility.assigned_units)),
    [facilities],
  )

  const laneUtilizationColor = (pct: number): Rgba => {
    if (pct > 100) return colors.destructive
    if (pct >= 95) return colors.warning
    return colors.success
  }

  const unmetDemandColor = (facility: NetworkFacilityAggregate): Rgba => {
    if (facility.facility_type === 'distribution_center') return colors.primary
    const demand = destinationDemand.get(facility.facility_id)?.demand ?? 0
    if (demand <= 0) return colors.muted
    const ratio = unmetByFacility.get(facility.facility_id) ?? 0
    if (ratio >= 0.1) return colors.destructive
    if (ratio > 0) return colors.warning
    return colors.success
  }

  const layers = useMemo(
    () => {
      const flowColor = (lane: NetworkLaneAggregate): Rgba =>
        laneUtilizationColor(lane.utilization_pct)
      const arcWidth = (lane: NetworkLaneAggregate) => {
        const base = 5 + Math.sqrt(lane.assigned_units / maxFlow) * 11
        return lane.lane_id === selectedLaneId ? base + 3 : base
      }
      const activeLanes = mapLanes.filter((lane) => lane.assigned_units > 0)
      const expressAir = activeLanes.filter((lane) => lane.mode.toUpperCase() === 'AIR')
      const linehaul = activeLanes.filter(
        (lane) => lane.lane_type === 'LINEHAUL' && lane.mode.toUpperCase() !== 'AIR',
      )
      const depots = facilities.filter((facility) => facility.facility_type === 'depot')
      const distributionCenters = facilities.filter((facility) => facility.facility_type === 'distribution_center')
      return [
        new PathLayer<NetworkLaneAggregate>({
          id: 'network-linehaul-lines',
          data: linehaul,
          getPath: (lane) => [
            [lane.origin_location.lng, lane.origin_location.lat],
            [lane.destination_location.lng, lane.destination_location.lat],
          ],
          getColor: flowColor,
          getWidth: arcWidth,
          widthUnits: 'pixels',
          widthMinPixels: 5,
          widthMaxPixels: 19,
          capRounded: true,
          jointRounded: true,
          pickable: true,
          autoHighlight: true,
          updateTriggers: {
            getColor: [colors],
            getWidth: [maxFlow, selectedLaneId],
          },
        }),
        new ArcLayer<NetworkLaneAggregate>({
          id: 'network-express-air-arcs',
          data: expressAir,
          getSourcePosition: (lane) => [lane.origin_location.lng, lane.origin_location.lat],
          getTargetPosition: (lane) => [lane.destination_location.lng, lane.destination_location.lat],
          getSourceColor: flowColor,
          getTargetColor: flowColor,
          getWidth: arcWidth,
          getHeight: (lane) => lane.lane_id === selectedLaneId ? 1.35 : 0.9 + laneOffset(lane.lane_id) * 0.35,
          getTilt: (lane) => 28 + laneOffset(lane.lane_id) * 34,
          widthUnits: 'pixels',
          widthMinPixels: 5,
          widthMaxPixels: 19,
          pickable: true,
          autoHighlight: true,
          greatCircle: false,
          updateTriggers: {
            getWidth: [maxFlow, selectedLaneId],
            getHeight: [selectedLaneId],
            getSourceColor: [colors],
            getTargetColor: [colors],
          },
        }),
        new TextLayer<NetworkLaneAggregate>({
          id: 'network-express-air-labels',
          data: expressAir,
          getPosition: (lane) => [
            (lane.origin_location.lng + lane.destination_location.lng) / 2,
            (lane.origin_location.lat + lane.destination_location.lat) / 2,
          ],
          getText: (lane) =>
            `${lane.origin_endpoint_name} → ${lane.destination_endpoint_name} · AIR · ${formatCurrency(lane.total_cost)}`,
          getColor: colors.foreground,
          getSize: 12,
          sizeUnits: 'pixels',
          getPixelOffset: [0, -14],
          background: true,
          getBackgroundColor: [15, 23, 42, 220],
          backgroundPadding: [5, 3],
          billboard: true,
          pickable: false,
        }),
        new ScatterplotLayer<NetworkFacilityAggregate>({
          id: 'network-depot-dots',
          data: depots,
          getPosition: (facility) => [facility.location.lng, facility.location.lat],
          getRadius: (facility) => 6 + Math.sqrt(facility.assigned_units / maxFacilityFlow) * 8 + (facility.facility_id === selectedFacilityId ? 3 : 0),
          radiusUnits: 'pixels',
          getFillColor: unmetDemandColor,
          filled: true,
          stroked: true,
          getLineColor: colors.foreground,
          getLineWidth: 1,
          lineWidthUnits: 'pixels',
          pickable: true,
          autoHighlight: true,
          updateTriggers: {
            getRadius: [maxFacilityFlow, selectedFacilityId],
            getFillColor: [destinationDemand, unmetByFacility, colors],
          },
        }),
        new TextLayer<NetworkFacilityAggregate>({
          id: 'network-distribution-center-squares',
          data: distributionCenters,
          getPosition: (facility) => [facility.location.lng, facility.location.lat],
          getText: () => '■',
          characterSet: ['■'],
          getColor: unmetDemandColor,
          getSize: (facility) => 18 + Math.sqrt(facility.assigned_units / maxFacilityFlow) * 16 + (facility.facility_id === selectedFacilityId ? 6 : 0),
          sizeUnits: 'pixels',
          billboard: true,
          pickable: true,
          autoHighlight: true,
          updateTriggers: {
            getColor: [destinationDemand, unmetByFacility, colors],
            getSize: [maxFacilityFlow, selectedFacilityId],
          },
        }),
      ]
    },
    [
      colors,
      facilities,
      mapLanes,
      maxFacilityFlow,
      maxFlow,
      selectedFacilityId,
      selectedLaneId,
      unmetByFacility,
      destinationDemand,
    ],
  )

  return (
    <div className="relative h-[620px] min-h-[620px] overflow-hidden rounded-lg border border-border bg-card xl:h-full">
      <div className="sr-only" aria-label="Facility unmet demand details">
        <h3>Facility unmet demand details</h3>
        <ul>
          {facilities.map((facility) => (
            <li key={facility.facility_id}>
              {facility.facility_name}, {facility.facility_type === 'distribution_center' ? 'distribution center' : 'depot'}: {(destinationDemand.get(facility.facility_id)?.demand ?? 0) > 0
                ? `${formatNumber(unmetCasesByFacility.get(facility.facility_id) ?? 0)} unmet cases at this target`
                : 'no target demand in this view'}.
            </li>
          ))}
        </ul>
      </div>
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
            return
          }
          if ('lane_id' in object) {
            onSelectLane(String((object as NetworkLaneAggregate).lane_id))
          }
        }}
        getTooltip={({ object }) => {
          if (!object) return null
          if ('facility_id' in object) {
            const facility = object as NetworkFacilityAggregate
            const unmet = unmetCasesByFacility.get(facility.facility_id) ?? 0
            const demand = destinationDemand.get(facility.facility_id)?.demand ?? 0
            return tooltip(`
              <strong>${escapeHtml(facility.facility_name)}</strong>
              <div>${facility.facility_type === 'distribution_center' ? 'Distribution center' : 'Depot'}</div>
              <div style="margin-top:4px">Available supply setting: ${facility.facility_type === 'depot' ? 'Unavailable — depots do not own stock' : facility.supply_retained_pct == null ? 'Unknown (legacy result)' : `${formatPercent(facility.supply_retained_pct)} of normal daily stock`}</div>
              ${facility.facility_type === 'distribution_center' && facility.normal_supply_units != null ? `<div>Normal daily local stock: ${formatNumber(facility.normal_supply_units)} cases</div>` : ''}
              ${facility.facility_type === 'distribution_center' && facility.supply_units != null ? `<div>Effective local stock after setting: ${formatNumber(facility.supply_units)} cases</div>` : ''}
              ${facility.facility_type === 'distribution_center' && facility.supply_available_units != null ? `<div>Solver-reported available supply: ${formatNumber(facility.supply_available_units)} cases (may include transfer arrivals)</div>` : ''}
              <div>Handling capacity: ${facility.handling_retained_pct == null ? 'Unknown (legacy result)' : `${formatPercent(facility.handling_retained_pct)} of normal daily handling${facility.handling_capacity_units == null ? '' : ` (${formatNumber(facility.handling_capacity_units)} normal)`}${facility.handling_available_units == null ? '' : ` · ${formatNumber(facility.handling_available_units)} available`}${facility.handling_utilization_pct == null ? '' : ` · ${formatPercent(facility.handling_utilization_pct)} used`}`}</div>
              ${facility.supply_source ? `<div>Supply source: ${escapeHtml(supplySourceLabel(facility.supply_source))}</div>` : ''}
              <div style="margin-top:4px">${formatNumber(facility.assigned_units)} assigned · ${formatPercent(facility.utilization_pct)} utilized</div>
              <div>${demand > 0 ? `${formatNumber(unmet)} unmet demand ${facility.facility_type === 'distribution_center' ? 'across its displayed depots' : 'at this target'} (${formatPercent(unmet / demand * 100)})` : 'No target demand in this view'}</div>
            `)
          }
          const lane = object as NetworkLaneAggregate
          return tooltip(`
            <strong>${escapeHtml(lane.lane_name)}</strong>
            <div>${escapeHtml(lane.origin_endpoint_name)} → ${escapeHtml(lane.destination_endpoint_name)}</div>
            <div style="margin-top:4px">Flow volume: ${formatNumber(lane.assigned_units)} cases</div>
            <div>Lane capacity: ${formatNumber(lane.capacity_units)} cases · ${formatPercent(lane.utilization_pct)} utilized</div>
            <div>${formatCurrency(lane.total_cost)} modeled cost</div>
            ${(lane.tariff_total ?? 0) > 0 ? `<div>Cross-border tariff exposure: ${formatCurrency(lane.tariff_total ?? 0)} on ${formatNumber(lane.assigned_units)} cases</div>` : ''}
          `)
        }}
      >
        <MapLibreMap
          reuseMaps
          mapStyle="https://basemaps.cartocdn.com/gl/dark-matter-gl-style/style.json"
        />
      </DeckGL>

      <div className="pointer-events-none absolute bottom-3 left-3 rounded-md border border-border bg-background/90 p-3 text-[11px] shadow-lg backdrop-blur">
        <div className="font-medium">Depot fill · unmet demand at target</div>
        <div className="mt-2 flex items-center gap-3 text-muted-foreground">
          <span className="flex items-center gap-1.5">
            <span className="h-1.5 w-4 rounded bg-success" /> 0% unmet
          </span>
          <span className="flex items-center gap-1.5">
            <span className="h-1.5 w-4 rounded bg-warning" /> &gt;0–&lt;10%
          </span>
          <span className="flex items-center gap-1.5">
            <span className="h-1.5 w-4 rounded bg-destructive" /> ≥10%
          </span>
        </div>
        <div className="mt-2 flex flex-col gap-1 border-t border-border pt-2 text-muted-foreground">
          <span className="flex items-center gap-1.5">
            <svg width="18" height="10" viewBox="0 0 18 10" aria-hidden>
              <line x1="1" y1="8" x2="17" y2="8" stroke="currentColor" strokeWidth="2" />
            </svg>
            Linehaul freight · flat
          </span>
          <span className="flex items-center gap-1.5">
            <svg width="18" height="10" viewBox="0 0 18 10" aria-hidden>
              <path d="M1 9 Q9 -3 17 9" fill="none" stroke="currentColor" strokeWidth="2" />
            </svg>
            Express AIR · elevated arc →
          </span>
        </div>
        <div className="mt-2 flex items-center gap-2 border-t border-border pt-2 text-muted-foreground">
          <span className="h-1.5 w-4 rounded bg-muted-foreground" /> Thin
          <span className="h-3 w-7 rounded bg-muted-foreground" /> Thick = volume
        </div>
        <div className="mt-2 flex items-center gap-3 border-t border-border pt-2 text-muted-foreground">
          <span className="flex items-center gap-1.5">
            <span className="text-base leading-none text-primary">■</span> DC
          </span>
          <span className="flex items-center gap-1.5">
            <span className="text-base leading-none">●</span> Depot
          </span>
        </div>
        <div className="mt-2 border-t border-border pt-2 text-muted-foreground">
          <div className="font-medium text-foreground">Lane color · utilization of capacity</div>
          <div className="mt-1 flex flex-wrap gap-x-3 gap-y-1">
            <span><span className="text-success">●</span> &lt;95%</span>
            <span><span className="text-warning">●</span> 95–100%</span>
            <span><span className="text-destructive">●</span> &gt;100%</span>
          </div>
        </div>
      </div>

      {!mapLanes.some((lane) => lane.assigned_units > 0) && (
        <div className="absolute inset-0 flex items-center justify-center bg-background/70 backdrop-blur-sm">
          <div className="rounded-md border border-border bg-card p-4 text-sm text-muted-foreground">
            No shipments in this planning context.
          </div>
        </div>
      )}
    </div>
  )
}

function supplySourceLabel(source: string) {
  if (source === 'canonical_daily_supply') return 'Canonical daily supply'
  if (source === 'legacy_handling_capacity_fallback') return 'Legacy fallback derived from handling capacity'
  return source
}

function laneOffset(laneId: string) {
  let hash = 0
  for (const character of laneId) hash = (hash * 31 + character.charCodeAt(0)) | 0
  return (Math.abs(hash) % 1000) / 999
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
