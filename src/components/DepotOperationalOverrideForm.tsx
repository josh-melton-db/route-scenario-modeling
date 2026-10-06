import { Plus, Trash2 } from 'lucide-react'
import { useState, type ReactNode } from 'react'
import DeliveryMapEditor from './DeliveryMapEditor'
import FacilityMapEditor from './FacilityMapEditor'
import MapView from './MapView'
import type { Depot, DepotPlanDailyChange, DepotPlanOverrideRequest, LatLng, Route, Stop } from '@/api/types'

export type OperationalDraft = Omit<DepotPlanOverrideRequest, 'route_scenario_id'> & {
  new_depot_location?: LatLng
}

export const emptyOperationalDraft: OperationalDraft = {
  driver_delta: 0,
  allow_overtime: false,
  changes: [],
}

export default function DepotOperationalOverrideForm({
  value,
  onChange,
  onOptimize,
  onReset,
  busy,
  canReset,
  canOptimize = true,
  depot,
  baselineRoutes,
}: {
  value: OperationalDraft
  onChange: (value: OperationalDraft) => void
  onOptimize: () => void
  onReset: () => void
  busy: boolean
  canReset: boolean
  canOptimize?: boolean
  depot: Depot
  baselineRoutes: Route[]
}) {
  const [showOperating, setShowOperating] = useState(false)
  const [showWindowMap, setShowWindowMap] = useState(false)
  const [selectedCustomerId, setSelectedCustomerId] = useState<string | null>(null)
  const stops = baselineRoutes.flatMap((route) => route.stops)
  const customers = [...new Map(stops.map((stop) => [stop.customer_id, stop])).values()]
    .sort((a, b) => a.customer_name.localeCompare(b.customer_name))
  const windowChanges = (value.changes ?? []).filter((change) => change.kind === 'time_window_change')
  const setNumber = (key: keyof OperationalDraft, raw: string) =>
    onChange({ ...value, [key]: raw === '' ? undefined : Number(raw) })
  const changes = value.changes ?? []
  const deliveryChange = changes.find((change) => change.kind === 'add_deliveries')
  const facilityChange = changes.find((change) => change.kind === 'facility_move')
  const hasInvalidLimits = ([
    [value.driver_delta, -64, 64],
    [value.max_route_minutes, 1, 1440],
    [value.max_stops_per_route, 1, 149],
  ] as const).some(([number, minimum, maximum]) => number != null && (!Number.isInteger(number) || number < minimum || number > maximum))
  const hasInvalidWindow = windowChanges.some((change) => !change.receiving_window_start || change.receiving_window_end <= change.receiving_window_start)
  const hasEmptyDeliveryChange = deliveryChange?.kind === 'add_deliveries' && deliveryChange.deliveries.length === 0
  const replaceChange = (kind: DepotPlanDailyChange['kind'], next: DepotPlanDailyChange) =>
    onChange({ ...value, changes: changes.map((change) => change.kind === kind ? next : change) })
  const removeChange = (kind: DepotPlanDailyChange['kind']) =>
    onChange({ ...value, changes: changes.filter((change) => change.kind !== kind) })
  function selectWindowStop(stop: Stop) {
    setSelectedCustomerId(stop.customer_id)
    if (!windowChanges.some((change) => change.customer_id === stop.customer_id)) {
      onChange({ ...value, changes: [...changes, {
        kind: 'time_window_change', customer_id: stop.customer_id,
        receiving_window_start: stop.time_window_start,
        receiving_window_end: stop.time_window_end,
      }] })
    }
  }

  return (
    <section className="rounded-lg border border-border bg-card p-4">
      <h2 className="text-sm font-semibold">Scenario changes</h2>
      <div className="mt-4 flex flex-wrap gap-2">
        {!deliveryChange && <button type="button" onClick={() => onChange({ ...value, changes: [...changes, { kind: 'add_deliveries', deliveries: [] }] })} className="inline-flex items-center gap-1 rounded-md border border-border px-2.5 py-1.5 text-xs hover:bg-accent/40"><Plus className="h-3.5 w-3.5" />Add deliveries</button>}
        {!facilityChange && <button type="button" onClick={() => onChange({ ...value, changes: [...changes, { kind: 'facility_move', new_depot_location: depot.location, preserve_service_windows: true }] })} className="inline-flex items-center gap-1 rounded-md border border-border px-2.5 py-1.5 text-xs hover:bg-accent/40"><Plus className="h-3.5 w-3.5" />Move facility</button>}
        <button type="button" disabled={!stops.length} onClick={() => {
          setShowWindowMap(true)
        }} className="inline-flex items-center gap-1 rounded-md border border-border px-2.5 py-1.5 text-xs disabled:opacity-50"><Plus className="h-3.5 w-3.5" />Delivery time window</button>
        {!showOperating && <button type="button" onClick={() => setShowOperating(true)} className="inline-flex items-center gap-1 rounded-md border border-border px-2.5 py-1.5 text-xs"><Plus className="h-3.5 w-3.5" />Drivers & route limits</button>}
      </div>
      {(showOperating || Boolean(value.driver_delta || value.max_route_minutes || value.max_stops_per_route || value.allow_overtime)) && <div className="mt-4 grid gap-3 sm:grid-cols-2 lg:grid-cols-3">
        <NumberField label="Driver delta" value={value.driver_delta} onChange={(raw) => setNumber('driver_delta', raw)} />
        <NumberField label="Max route minutes" value={value.max_route_minutes} onChange={(raw) => setNumber('max_route_minutes', raw)} />
        <NumberField label="Max stops per route" value={value.max_stops_per_route} onChange={(raw) => setNumber('max_stops_per_route', raw)} />
        <label className="flex items-center gap-2 rounded-md border border-border px-3 py-2 text-sm">
          <input
            type="checkbox"
            checked={value.allow_overtime ?? false}
            onChange={(event) => onChange({ ...value, allow_overtime: event.target.checked })}
          />
          Allow overtime
        </label>
      </div>}
      {deliveryChange?.kind === 'add_deliveries' && <ChangeCard title="Add deliveries" onRemove={() => removeChange('add_deliveries')}>
        <DeliveryMapEditor depot={depot} baselineRoutes={baselineRoutes} deliveries={deliveryChange.deliveries} onChange={(deliveries) => replaceChange('add_deliveries', { kind: 'add_deliveries', deliveries })} />
      </ChangeCard>}
      {facilityChange?.kind === 'facility_move' && <ChangeCard title="Move facility" onRemove={() => removeChange('facility_move')}>
        <FacilityMapEditor showServiceWindowOption={false} depot={depot} baselineRoutes={baselineRoutes} location={facilityChange.new_depot_location} preserveServiceWindows={facilityChange.preserve_service_windows} onLocationChange={(new_depot_location) => replaceChange('facility_move', { ...facilityChange, new_depot_location })} onPreserveServiceWindowsChange={(preserve_service_windows) => replaceChange('facility_move', { ...facilityChange, preserve_service_windows })} />
      </ChangeCard>}
      {(showWindowMap || windowChanges.length > 0) && <ChangeCard title="Delivery time windows" onRemove={() => {
        removeChange('time_window_change')
        setShowWindowMap(false)
        setSelectedCustomerId(null)
      }}>
        <p className="mb-3 text-xs text-muted-foreground">Choose a customer by name or click a delivery pin to set its receiving window. Select more deliveries to change multiple windows.</p>
        <label className="mb-3 block text-xs text-muted-foreground">
          Customer name
          <select aria-label="Customer name" value={selectedCustomerId ?? ''} onChange={(event) => {
            const stop = customers.find((row) => row.customer_id === event.target.value)
            if (stop) selectWindowStop(stop)
          }} className="mt-1 block h-10 w-full rounded-md border border-border bg-background px-2 text-sm text-foreground">
            <option value="" disabled>Select a customer…</option>
            {customers.map((stop) => <option key={stop.customer_id} value={stop.customer_id}>{stop.customer_name}</option>)}
          </select>
        </label>
        <div className="h-[360px]" aria-label="Delivery time window map">
          <MapView depot={depot} routes={baselineRoutes} selectedRouteId={null}
            onSelectRoute={() => undefined} onSelectStop={selectWindowStop}
            selectedCustomerId={selectedCustomerId} />
        </div>
        {windowChanges.length === 0 && <p className="mt-3 text-sm text-muted-foreground">Select a delivery to add a window.</p>}
      {windowChanges.map((change, index) => <div key={change.customer_id} className={`mt-3 rounded-md border p-3 ${selectedCustomerId === change.customer_id ? 'border-primary' : 'border-border'}`}>
        <div className="mb-2 flex items-center justify-between">
          <button type="button" className="text-sm font-medium" onClick={() => setSelectedCustomerId(change.customer_id)}>{stops.find((stop) => stop.customer_id === change.customer_id)?.customer_name ?? change.customer_id}</button>
          <button type="button" aria-label={`Remove window for ${stops.find((stop) => stop.customer_id === change.customer_id)?.customer_name ?? change.customer_id}`} onClick={() => onChange({ ...value, changes: changes.filter((row) => row !== change) })} className="text-xs text-muted-foreground hover:text-destructive">Remove</button>
        </div>
        <div className="grid gap-3 sm:grid-cols-2">
          {(['receiving_window_start', 'receiving_window_end'] as const).map((field) => <label key={field} className="text-xs">{field === 'receiving_window_start' ? 'Opens' : 'Closes'}
            <input type="time" aria-label={`Delivery ${index + 1} ${field === 'receiving_window_start' ? 'opens' : 'closes'}`} value={change[field]} onChange={(event) => onChange({ ...value, changes: changes.map((row) => row === change ? { ...change, [field]: event.target.value } : row) })} className="mt-1 block h-10 w-full rounded-md border border-border bg-background px-2" />
          </label>)}
        </div>
      </div>)}
      </ChangeCard>}
      {hasInvalidLimits && <p role="alert" className="mt-3 text-xs text-destructive">Use whole numbers: drivers −64 to64, route minutes1–1440, stops1–149.</p>}
      {hasInvalidWindow && <p role="alert" className="mt-3 text-xs text-destructive">Closing time must be after opening time.</p>}
      {hasEmptyDeliveryChange && <p className="mt-3 text-xs text-amber-600 dark:text-amber-400">Drop at least one delivery pin before optimizing.</p>}
      <div className="mt-4 flex flex-wrap justify-end gap-2">
        <button type="button" onClick={onReset} disabled={!canReset || busy} className="rounded-md border border-border px-3 py-2 text-sm disabled:opacity-50">
          Reset selected day to default
        </button>
        <button type="button" onClick={onOptimize} disabled={busy || !canOptimize || hasEmptyDeliveryChange || hasInvalidWindow || hasInvalidLimits} className="rounded-md bg-primary px-3 py-2 text-sm font-semibold text-primary-foreground disabled:opacity-50">
          {busy ? 'Queueing…' : 'Run scenario'}
        </button>
      </div>
    </section>
  )
}

function ChangeCard({ title, onRemove, children }: { title: string; onRemove: () => void; children: ReactNode }) {
  return <div className="mt-4 rounded-lg border border-border bg-background/30 p-3"><div className="mb-3 flex items-center justify-between"><h3 className="text-sm font-semibold">{title}</h3><button type="button" onClick={onRemove} className="inline-flex items-center gap-1 rounded-md border border-border px-2 py-1 text-xs text-muted-foreground hover:text-destructive"><Trash2 className="h-3.5 w-3.5" />Remove</button></div>{children}</div>
}

function NumberField({ label, value, onChange }: { label: string; value?: number; onChange: (value: string) => void }) {
  return (
    <label className="text-sm">
      <span className="mb-1 block text-xs text-muted-foreground">{label}</span>
      <input type="number" value={value ?? ''} onChange={(event) => onChange(event.target.value)} className="h-10 w-full rounded-md border border-border bg-background px-3" />
    </label>
  )
}
