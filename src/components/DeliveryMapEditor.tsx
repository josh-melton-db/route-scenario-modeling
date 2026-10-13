import { useMemo, useState, useRef } from 'react'
import { Loader2, Trash2 } from 'lucide-react'
import { api } from '@/api/client'
import MapView from '@/components/MapView'
import type { DeliveryDraft, Depot, Route } from '@/api/types'

interface DeliveryMapEditorProps {
  onCheckingChange?: (checking: boolean) => void
  planSetId?: string
  depot: Depot
  baselineRoutes?: Route[]
  deliveries: DeliveryDraft[]
  onChange: (deliveries: DeliveryDraft[]) => void
}

const DEFAULT_DRAFT: Omit<DeliveryDraft, 'lat' | 'lng' | 'customer_name'> = {
  demand_cases: 80,
  service_minutes: 30,
  receiving_window_start: '08:00',
  receiving_window_end: '16:00',
}

export default function DeliveryMapEditor({
  depot,
  planSetId,
  onCheckingChange,
  baselineRoutes = [],
  deliveries,
  onChange,
}: DeliveryMapEditorProps) {
  const [selectedIndex, setSelectedIndex] = useState<number | null>(null)
  const [clearConfirmation, setClearConfirmation] = useState(false)
  const selected = useMemo(
    () => (selectedIndex === null ? null : deliveries[selectedIndex] ?? null),
    [deliveries, selectedIndex],
  )

  const currentDeliveries = useRef(deliveries)
  currentDeliveries.current = deliveries
  const accessPending = useRef(false)
  const [checking, setChecking] = useState(false)
  const [accessMessage, setAccessMessage] = useState<string | null>(null)
  async function addDeliveries(rows: DeliveryDraft[]) {
    if (accessPending.current) return
    accessPending.current = true
    setChecking(true)
    onCheckingChange?.(true)
    setAccessMessage(null)
    try {
      const checked: DeliveryDraft[] = []
      let moved = 0
      for (const row of rows) {
        if (!Number.isFinite(row.lat) || Math.abs(row.lat) > 90 || !Number.isFinite(row.lng) || Math.abs(row.lng) > 180 || !Number.isInteger(row.demand_cases) || row.demand_cases < 1) throw new Error('Each delivery needs valid latitude, longitude, and a positive whole-number case quantity.')
        if (planSetId) {
          const access = await api.depotDeliveryAccess(planSetId, row)
          if (!access.reachable) throw new Error(`${row.customer_name}: ${access.reason === 'coverage_unavailable' ? 'Truck-road validation is unavailable for this area.' : access.reason === 'snap_distance_exceeded' ? 'The nearest reachable road is too far away.' : 'No reachable truck-road path from this depot.'} Delivery was not added.`)
          checked.push({ ...row, lat: access.road_access_lat ?? row.lat, lng: access.road_access_lng ?? row.lng })
          if ((access.road_snap_distance_miles ?? 0) > 0) moved++
        } else checked.push(row)
      }
      onChange([...currentDeliveries.current, ...checked])
      setSelectedIndex(currentDeliveries.current.length)
      setClearConfirmation(false)
      setAccessMessage(planSetId ? `${checked.length} deliveries checked for truck-road access; ${moved} snapped to the road.` : 'Deliveries added; road access has not been checked.')
    } catch (error) { setAccessMessage(String(error)) }
    finally { accessPending.current = false; setChecking(false); onCheckingChange?.(false) }
  }
  function handleMapClick(lngLat: { lat: number; lng: number }) {
    void addDeliveries([{ ...DEFAULT_DRAFT, customer_name: `Manual Delivery ${deliveries.length + 1}`, ...lngLat }])
  }
  async function upload(file: File) {
    try {
      let rows: DeliveryDraft[]
      if (file.name.toLowerCase().endsWith('.xlsx')) {
        const parsed = await api.uploadDeliveries(file)
        if (parsed.errors.length) throw new Error(parsed.errors.map(row => `Row ${row.row}: ${row.message}`).join('; '))
        rows = parsed.deliveries
      } else rows = parseDeliveryCsv(await file.text())
      await addDeliveries(rows)
    } catch (error) { setAccessMessage(String(error)) }
  }

  function updateSelected(patch: Partial<DeliveryDraft>) {
    if (selectedIndex === null) return
    onChange(
      deliveries.map((row, index) =>
        index === selectedIndex ? { ...row, ...patch } : row,
      ),
    )
  }

  function removeSelected() {
    if (selectedIndex === null) return
    onChange(deliveries.filter((_, index) => index !== selectedIndex))
    setSelectedIndex(null)
    setClearConfirmation(false)
  }

  function clearAll() {
    onChange([])
    setSelectedIndex(null)
    setClearConfirmation(false)
  }

  return (
    <div className="grid gap-3 lg:grid-cols-[1.4fr_1fr]">
      <div className="h-[360px]">
        <MapView
          depot={depot}
          routes={baselineRoutes}
          selectedRouteId={null}
          onSelectRoute={() => undefined}
          editable
          draftStops={deliveries}
          selectedDraftIndex={selectedIndex}
          onMapClick={handleMapClick}
          onSelectDraftStop={setSelectedIndex}
        />
      </div>
      <div className="rounded-lg border border-border bg-card p-3">
        <div className="text-sm font-semibold">Delivery pin details</div>
        <label className="mt-2 block text-xs">Upload deliveries (CSV or Excel; lat, lng, demand_cases, customer_name)
          <input aria-label="Upload delivery CSV" type="file" accept=".csv,.xlsx,text/csv" disabled={checking} onChange={event => { const file = event.target.files?.[0]; if (file) void upload(file); event.target.value = '' }} className="mt-1 block w-full" />
        </label>
        {checking && <p role="status" className="mt-2 flex items-center gap-2 text-xs"><Loader2 className="h-4 w-4 animate-spin" />Checking truck-road access…</p>}
        {accessMessage && <p role="status" className="mt-2 text-xs">{accessMessage}</p>}
        <p className="mt-1 text-xs text-muted-foreground">
          {deliveries.length} pin{deliveries.length === 1 ? '' : 's'} on the map.
          Click a pin to edit attributes.
        </p>
        {deliveries.length > 0 && (
          <div className="mt-3">
            {clearConfirmation ? (
              <div className="flex flex-wrap items-center gap-2 rounded-md border border-destructive/40 bg-destructive/10 p-2 text-xs text-destructive">
                <span>Clear all {deliveries.length} draft pins?</span>
                <button
                  type="button"
                  onClick={() => setClearConfirmation(false)}
                  className="rounded border border-border bg-background px-2 py-1 text-foreground"
                >
                  Cancel
                </button>
                <button
                  type="button"
                  onClick={clearAll}
                  className="rounded bg-destructive px-2 py-1 font-medium text-destructive-foreground"
                >
                  Clear all
                </button>
              </div>
            ) : (
              <button
                type="button"
                onClick={() => setClearConfirmation(true)}
                className="inline-flex items-center gap-1 text-xs text-muted-foreground underline hover:text-destructive"
              >
                <Trash2 className="h-3.5 w-3.5" />
                Clear all
              </button>
            )}
          </div>
        )}
        {selected ? (
          <div className="mt-3 flex flex-col gap-2 text-sm">
            <label className="flex flex-col gap-1">
              <span className="text-xs text-muted-foreground">Name</span>
              <input
                className="rounded-md border border-border bg-background px-2 py-1.5"
                value={selected.customer_name}
                onChange={(event) =>
                  updateSelected({ customer_name: event.target.value })
                }
              />
            </label>
            <div className="grid grid-cols-2 gap-2">
              <label className="flex flex-col gap-1">
                <span className="text-xs text-muted-foreground">Cases</span>
                <input
                  type="number"
                  className="rounded-md border border-border bg-background px-2 py-1.5"
                  min={1}
                  step={1}
                  value={selected.demand_cases}
                  onChange={(event) =>
                    updateSelected({
                      demand_cases: Number.parseInt(event.target.value, 10) || 0,
                    })
                  }
                />
              </label>
              <label className="flex flex-col gap-1">
                <span className="text-xs text-muted-foreground">Service min</span>
                <input
                  type="number"
                  className="rounded-md border border-border bg-background px-2 py-1.5"
                  value={selected.service_minutes}
                  onChange={(event) =>
                    updateSelected({
                      service_minutes:
                        Number.parseInt(event.target.value, 10) || 0,
                    })
                  }
                />
              </label>
            </div>
            <div className="grid grid-cols-2 gap-2">
              <label className="flex flex-col gap-1">
                <span className="text-xs text-muted-foreground">Window start</span>
                <input
                  className="rounded-md border border-border bg-background px-2 py-1.5"
                  value={selected.receiving_window_start}
                  onChange={(event) =>
                    updateSelected({ receiving_window_start: event.target.value })
                  }
                />
              </label>
              <label className="flex flex-col gap-1">
                <span className="text-xs text-muted-foreground">Window end</span>
                <input
                  className="rounded-md border border-border bg-background px-2 py-1.5"
                  value={selected.receiving_window_end}
                  onChange={(event) =>
                    updateSelected({ receiving_window_end: event.target.value })
                  }
                />
              </label>
            </div>
            <div className="text-xs text-muted-foreground">
              {selected.lat.toFixed(5)}, {selected.lng.toFixed(5)}
            </div>
            <button
              type="button"
              onClick={removeSelected}
              className="mt-1 inline-flex items-center justify-center gap-1 rounded-md border border-destructive/40 bg-destructive/10 px-2 py-1.5 text-xs text-destructive"
            >
              <Trash2 className="h-3.5 w-3.5" />
              Remove pin
            </button>
          </div>
        ) : (
          <div className="mt-4 text-sm text-muted-foreground">
            Drop pins on the map, then select one to edit demand and windows.
          </div>
        )}
      </div>
    </div>
  )
}

export function parseDeliveryCsv(text: string): DeliveryDraft[] {
  const records: string[][] = []; let row: string[] = [], cell = '', quoted = false
  for (let i = 0; i < text.length; i++) {
    const char = text[i]
    if (char === '"') { if (quoted && text[i + 1] === '"') { cell += '"'; i++ } else quoted = !quoted }
    else if (!quoted && (char === ',' || char === '\n')) { row.push(cell.trim()); cell = ''; if (char === '\n') { records.push(row); row = [] } }
    else if (char !== '\r' || quoted) cell += char
  }
  if (quoted) throw new Error('CSV has an unterminated quoted field.')
  if (cell || row.length) { row.push(cell.trim()); records.push(row) }
  const headers = records.shift()?.map(value => value.replace(/^\uFEFF/, '').toLowerCase()) ?? []
  for (const required of ['lat', 'lng', 'demand_cases']) if (!headers.includes(required)) throw new Error(`CSV needs a ${required} column.`)
  const deliveries = records.filter(record => record.some(Boolean)).map((record, index) => {
    const get = (key: string) => record[headers.indexOf(key)] ?? ''
    if (!get('lat') || !get('lng') || !get('demand_cases')) throw new Error(`CSV row ${index + 2} is missing coordinates or case quantity.`)
    return { ...DEFAULT_DRAFT, lat: Number(get('lat')), lng: Number(get('lng')), demand_cases: Number(get('demand_cases')), customer_name: get('customer_name') || `Uploaded Delivery ${index + 1}` }
  })
  if (!deliveries.length) throw new Error('CSV has no deliveries.')
  if (deliveries.length > 149) throw new Error('Upload at most 149 deliveries at a time.')
  return deliveries
}
