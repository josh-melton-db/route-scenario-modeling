import type { DepotPlanOverrideRequest, LatLng } from '@/api/types'

export type OperationalDraft = Omit<DepotPlanOverrideRequest, 'route_scenario_id'> & {
  new_depot_location?: LatLng
}

export const emptyOperationalDraft: OperationalDraft = {
  driver_delta: 0,
  allow_overtime: false,
}

export default function DepotOperationalOverrideForm({
  value,
  onChange,
  onOptimize,
  onReset,
  busy,
  canReset,
}: {
  value: OperationalDraft
  onChange: (value: OperationalDraft) => void
  onOptimize: () => void
  onReset: () => void
  busy: boolean
  canReset: boolean
}) {
  const setNumber = (key: keyof OperationalDraft, raw: string) =>
    onChange({ ...value, [key]: raw === '' ? undefined : Number(raw) })

  return (
    <section className="rounded-lg border border-border bg-card p-4">
      <h2 className="text-sm font-semibold">Daily operational override</h2>
      <p className="mt-1 text-xs text-muted-foreground">
        Changes apply only to the selected service date. Untouched dates keep their stored defaults.
      </p>
      <div className="mt-4 grid gap-3 sm:grid-cols-2 lg:grid-cols-3">
        <NumberField label="Driver delta" value={value.driver_delta} onChange={(raw) => setNumber('driver_delta', raw)} />
        <NumberField label="Max route minutes" value={value.max_route_minutes} onChange={(raw) => setNumber('max_route_minutes', raw)} />
        <NumberField label="Max stops per route" value={value.max_stops_per_route} onChange={(raw) => setNumber('max_stops_per_route', raw)} />
        <NumberField label="New depot latitude" value={value.new_depot_location?.lat} onChange={(raw) => onChange({
          ...value,
          new_depot_location: raw === '' && value.new_depot_location?.lng == null ? undefined : {
            lat: raw === '' ? 0 : Number(raw),
            lng: value.new_depot_location?.lng ?? 0,
          },
        })} />
        <NumberField label="New depot longitude" value={value.new_depot_location?.lng} onChange={(raw) => onChange({
          ...value,
          new_depot_location: raw === '' && value.new_depot_location?.lat == null ? undefined : {
            lat: value.new_depot_location?.lat ?? 0,
            lng: raw === '' ? 0 : Number(raw),
          },
        })} />
        <label className="flex items-center gap-2 rounded-md border border-border px-3 py-2 text-sm">
          <input
            type="checkbox"
            checked={value.allow_overtime ?? false}
            onChange={(event) => onChange({ ...value, allow_overtime: event.target.checked })}
          />
          Allow overtime
        </label>
      </div>
      <div className="mt-4 flex flex-wrap justify-end gap-2">
        <button type="button" onClick={onReset} disabled={!canReset || busy} className="rounded-md border border-border px-3 py-2 text-sm disabled:opacity-50">
          Reset selected day to default
        </button>
        <button type="button" onClick={onOptimize} disabled={busy} className="rounded-md bg-primary px-3 py-2 text-sm font-semibold text-primary-foreground disabled:opacity-50">
          {busy ? 'Queueing…' : 'Optimize selected day'}
        </button>
      </div>
    </section>
  )
}

function NumberField({ label, value, onChange }: { label: string; value?: number; onChange: (value: string) => void }) {
  return (
    <label className="text-sm">
      <span className="mb-1 block text-xs text-muted-foreground">{label}</span>
      <input type="number" value={value ?? ''} onChange={(event) => onChange(event.target.value)} className="h-10 w-full rounded-md border border-border bg-background px-3" />
    </label>
  )
}
