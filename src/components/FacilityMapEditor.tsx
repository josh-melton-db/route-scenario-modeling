import { RotateCcw, Warehouse } from 'lucide-react'
import MapView from '@/components/MapView'
import type { Depot, LatLng, Route } from '@/api/types'

interface FacilityMapEditorProps {
  depot: Depot
  baselineRoutes?: Route[]
  location: LatLng
  preserveServiceWindows: boolean
  onLocationChange: (location: LatLng) => void
  onPreserveServiceWindowsChange: (preserve: boolean) => void
}

export default function FacilityMapEditor({
  depot,
  baselineRoutes = [],
  location,
  preserveServiceWindows,
  onLocationChange,
  onPreserveServiceWindowsChange,
}: FacilityMapEditorProps) {
  const isCurrentLocation =
    location.lat === depot.location.lat && location.lng === depot.location.lng

  function updateCoordinate(axis: keyof LatLng, rawValue: string) {
    const value = Number.parseFloat(rawValue)
    if (!Number.isFinite(value)) return
    onLocationChange({ ...location, [axis]: value })
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
          proposedDepotLocation={isCurrentLocation ? null : location}
          editInstruction="Click the map to place the proposed distribution center"
          onMapClick={(nextLocation) =>
            onLocationChange({
              lat: Number(nextLocation.lat.toFixed(6)),
              lng: Number(nextLocation.lng.toFixed(6)),
            })
          }
        />
      </div>
      <div className="rounded-lg border border-border bg-card p-3">
        <div className="flex items-center gap-2 text-sm font-semibold">
          <Warehouse className="h-4 w-4 text-primary" />
          Proposed distribution center
        </div>
        <p className="mt-1 text-xs text-muted-foreground">
          Click anywhere on the map to relocate the current center or evaluate a
          new operating location. The yellow marker is the proposed site.
        </p>

        <div className="mt-4 flex flex-col gap-3">
          <div className="rounded-md border border-border bg-muted/30 p-2 text-xs">
            <div className="font-medium">Current: {depot.name}</div>
            <div className="mt-0.5 text-muted-foreground">
              {depot.location.lat.toFixed(5)}, {depot.location.lng.toFixed(5)}
            </div>
          </div>

          <div className="grid grid-cols-2 gap-2">
            <label className="flex flex-col gap-1">
              <span className="text-xs text-muted-foreground">Proposed latitude</span>
              <input
                type="number"
                step={0.0001}
                value={location.lat}
                onChange={(event) => updateCoordinate('lat', event.target.value)}
                className="rounded-md border border-border bg-background px-2 py-1.5 text-sm"
              />
            </label>
            <label className="flex flex-col gap-1">
              <span className="text-xs text-muted-foreground">Proposed longitude</span>
              <input
                type="number"
                step={0.0001}
                value={location.lng}
                onChange={(event) => updateCoordinate('lng', event.target.value)}
                className="rounded-md border border-border bg-background px-2 py-1.5 text-sm"
              />
            </label>
          </div>

          <label className="flex items-start gap-2 text-sm">
            <input
              type="checkbox"
              checked={preserveServiceWindows}
              onChange={(event) =>
                onPreserveServiceWindowsChange(event.target.checked)
              }
              className="mt-0.5 h-4 w-4 rounded border-border"
            />
            <span>
              Preserve customer service windows
              <span className="block text-xs text-muted-foreground">
                Keep existing receiving windows when routes are recalculated.
              </span>
            </span>
          </label>

          <button
            type="button"
            disabled={isCurrentLocation}
            onClick={() => onLocationChange(depot.location)}
            className="inline-flex items-center justify-center gap-1 rounded-md border border-border px-2 py-1.5 text-xs text-muted-foreground disabled:cursor-not-allowed disabled:opacity-50"
          >
            <RotateCcw className="h-3.5 w-3.5" />
            Reset to current location
          </button>
        </div>
      </div>
    </div>
  )
}
