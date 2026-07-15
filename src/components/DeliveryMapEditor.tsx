import { useMemo, useState } from 'react'
import { Trash2 } from 'lucide-react'
import MapView from '@/components/MapView'
import type { DeliveryDraft, Depot, Route } from '@/api/types'

interface DeliveryMapEditorProps {
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

  function handleMapClick(lngLat: { lat: number; lng: number }) {
    const next: DeliveryDraft = {
      ...DEFAULT_DRAFT,
      customer_name: `Manual Delivery ${deliveries.length + 1}`,
      lat: Number(lngLat.lat.toFixed(6)),
      lng: Number(lngLat.lng.toFixed(6)),
    }
    const nextDeliveries = [...deliveries, next]
    onChange(nextDeliveries)
    setSelectedIndex(nextDeliveries.length - 1)
    setClearConfirmation(false)
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
