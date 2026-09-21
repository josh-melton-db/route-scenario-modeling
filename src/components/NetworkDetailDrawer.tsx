import { Link } from 'react-router-dom'
import {
  ArrowRight,
  Building2,
  ExternalLink,
  MapPin,
  Route,
  ScrollText,
  X,
} from 'lucide-react'
import type {
  NetworkFacilityAggregate,
  NetworkLaneAggregate,
} from '@/api/types'
import { formatCurrency, formatNumber, formatPercent } from '@/lib/format'

interface NetworkDetailDrawerProps {
  facility: NetworkFacilityAggregate | null
  lane: NetworkLaneAggregate | null
  depotAnalysisHref: string | null
  onClose: () => void
  onSelectFacility: (facilityId: string) => void
}

export default function NetworkDetailDrawer({
  facility,
  lane,
  depotAnalysisHref,
  onClose,
  onSelectFacility,
}: NetworkDetailDrawerProps) {
  if (!facility && !lane) return null

  return (
    <div className="fixed inset-0 top-16 z-40 bg-background/40" onMouseDown={onClose}>
      <aside
        role="dialog"
        aria-modal="true"
        aria-label={facility ? `${facility.facility_name} details` : `${lane?.lane_name} details`}
        className="ml-auto flex h-full w-full max-w-md flex-col border-l border-border bg-card shadow-2xl"
        onMouseDown={(event) => event.stopPropagation()}
      >
        <div className="flex items-start justify-between gap-3 border-b border-border p-4">
          <div className="flex min-w-0 items-start gap-3">
            <div className="rounded-md bg-primary/15 p-2 text-primary">
              {facility ? <Building2 className="h-4 w-4" /> : <Route className="h-4 w-4" />}
            </div>
            <div className="min-w-0">
              <h2 className="font-semibold">{facility?.facility_name ?? lane?.lane_name}</h2>
              <p className="mt-1 text-xs capitalize text-muted-foreground">
                {facility
                  ? facility.facility_type.replaceAll('_', ' ')
                  : `${lane?.lane_type.toLowerCase()} · ${lane?.mode}`}
              </p>
            </div>
          </div>
          <button
            type="button"
            aria-label="Close details"
            onClick={onClose}
            className="rounded-md p-1.5 text-muted-foreground hover:bg-accent hover:text-foreground"
          >
            <X className="h-4 w-4" />
          </button>
        </div>

        <div className="min-h-0 flex-1 overflow-y-auto p-4">
          {facility ? (
            <FacilityDetails facility={facility} />
          ) : lane ? (
            <LaneDetails lane={lane} onSelectFacility={onSelectFacility} />
          ) : null}
        </div>

        <div className="space-y-2 border-t border-border p-4">
          {facility?.facility_type === 'depot' && depotAnalysisHref ? (
            <Link
              to={depotAnalysisHref}
              className="flex w-full items-center justify-center gap-2 rounded-md bg-primary px-3 py-2 text-sm font-semibold text-primary-foreground"
            >
              Open depot analysis <ExternalLink className="h-4 w-4" />
            </Link>
          ) : facility?.facility_type === 'depot' ? (
            <div className="rounded-md border border-border bg-background/40 p-3 text-xs text-muted-foreground">
              Detailed route data is not available for this synthetic depot yet.
            </div>
          ) : null}
          {lane?.contract_id && lane.contract_version_id ? (
            <Link
              to={`/rates/contracts/${encodeURIComponent(lane.contract_id)}/versions/${encodeURIComponent(lane.contract_version_id)}/lane-rates`}
              className="flex w-full items-center justify-center gap-2 rounded-md border border-border px-3 py-2 text-sm font-medium hover:bg-accent"
            >
              <ScrollText className="h-4 w-4" /> Inspect rate book
            </Link>
          ) : null}
        </div>
      </aside>
    </div>
  )
}

function FacilityDetails({ facility }: { facility: NetworkFacilityAggregate }) {
  return (
    <div className="space-y-5">
      <div className="grid grid-cols-2 gap-3">
        <Metric label="Demand" value={`${formatNumber(facility.demand_units)} cases`} />
        <Metric label="Assigned flow" value={`${formatNumber(facility.assigned_units)} cases`} />
        <Metric label="Supplied capacity" value={`${formatNumber(facility.capacity_units)} cases`} />
        <Metric label="Utilization" value={formatPercent(facility.utilization_pct)} />
        <Metric label="Modeled cost" value={formatCurrency(facility.total_cost)} />
        <Metric label="On-time outlook" value={formatPercent(facility.on_time_pct)} />
      </div>
      <section className="rounded-md border border-border bg-background/40 p-3">
        <h3 className="text-xs font-medium">Network role</h3>
        <dl className="mt-3 space-y-2 text-xs">
          <DetailRow label="Facility ID" value={facility.facility_id} mono />
          <DetailRow
            label="Connected facilities"
            value={formatNumber(facility.connected_facility_count)}
          />
          {facility.facility_type === 'distribution_center' && (
            <DetailRow label="Depots served" value={formatNumber(facility.depot_count)} />
          )}
          {facility.parent_facility_id && (
            <DetailRow label="Parent DC" value={facility.parent_facility_id} mono />
          )}
        </dl>
      </section>
    </div>
  )
}

function LaneDetails({
  lane,
  onSelectFacility,
}: {
  lane: NetworkLaneAggregate
  onSelectFacility: (facilityId: string) => void
}) {
  return (
    <div className="space-y-5">
      <section className="rounded-md border border-border bg-background/40 p-3">
        <div className="flex items-center gap-2 text-xs">
          <MapPin className="h-3.5 w-3.5 text-primary" />
          <button
            type="button"
            disabled={lane.origin_endpoint_type !== 'facility'}
            onClick={() => onSelectFacility(lane.origin_endpoint_id)}
            className="min-w-0 truncate font-medium enabled:hover:text-primary"
          >
            {lane.origin_endpoint_name}
          </button>
          <ArrowRight className="h-3.5 w-3.5 flex-shrink-0 text-muted-foreground" />
          <button
            type="button"
            disabled={lane.destination_endpoint_type !== 'facility'}
            onClick={() => onSelectFacility(lane.destination_endpoint_id)}
            className="min-w-0 truncate font-medium enabled:hover:text-primary"
          >
            {lane.destination_endpoint_name}
          </button>
        </div>
      </section>
      <div className="grid grid-cols-2 gap-3">
        <Metric label="Assigned flow" value={`${formatNumber(lane.assigned_units)} cases`} />
        <Metric label="Supplied capacity" value={`${formatNumber(lane.capacity_units)} cases`} />
        <Metric label="Utilization" value={formatPercent(lane.utilization_pct)} />
        <Metric label="On-time outlook" value={formatPercent(lane.on_time_pct)} />
        <Metric label="Modeled cost" value={formatCurrency(lane.total_cost)} />
        <Metric
          label="Cost per case"
          value={lane.cost_per_unit.toLocaleString(undefined, {
            style: 'currency',
            currency: 'USD',
            minimumFractionDigits: 2,
            maximumFractionDigits: 2,
          })}
        />
      </div>
      <section className="rounded-md border border-border bg-background/40 p-3">
        <h3 className="text-xs font-medium">Lane definition</h3>
        <dl className="mt-3 space-y-2 text-xs">
          <DetailRow label="Lane ID" value={lane.lane_id} mono />
          <DetailRow label="Distance" value={`${formatNumber(lane.distance_miles, 1)} miles`} />
          <DetailRow label="Transit" value={`${formatNumber(lane.transit_minutes)} minutes`} />
          <DetailRow
            label="Rate coverage"
            value={lane.contract_coverage.replaceAll('_', ' ')}
          />
          <DetailRow
            label="Network total"
            value={lane.included_in_network_cost ? 'Included' : 'Allocation layer only'}
          />
        </dl>
      </section>
    </div>
  )
}

function Metric({ label, value }: { label: string; value: string }) {
  return (
    <div className="rounded-md border border-border bg-background/40 p-3">
      <div className="text-[10px] uppercase tracking-wide text-muted-foreground">{label}</div>
      <div className="mt-1 text-sm font-semibold tabular-nums">{value}</div>
    </div>
  )
}

function DetailRow({
  label,
  value,
  mono = false,
}: {
  label: string
  value: string
  mono?: boolean
}) {
  return (
    <div className="flex items-start justify-between gap-4">
      <dt className="text-muted-foreground">{label}</dt>
      <dd className={mono ? 'break-all text-right font-mono text-[11px]' : 'text-right capitalize'}>
        {value}
      </dd>
    </div>
  )
}
