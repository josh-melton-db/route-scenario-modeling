import type { OperatingConstraints, TransportationChoices } from '@/api/types'

interface Props {
  constraints: OperatingConstraints
  choices: TransportationChoices
  onConstraintsChange: (value: OperatingConstraints) => void
  onChoicesChange: (value: TransportationChoices) => void
}

export default function TransportationOptionsPanel({
  constraints,
  choices,
  onConstraintsChange,
  onChoicesChange,
}: Props) {
  const constraintNumber = (key: keyof OperatingConstraints, value: string) =>
    onConstraintsChange({ ...constraints, [key]: Number(value) })
  const choiceNumber = (key: keyof TransportationChoices, value: string) =>
    onChoicesChange({ ...choices, [key]: Number(value) })

  return (
    <div className="grid gap-4 xl:grid-cols-2">
      <section className="rounded-lg border border-border bg-card p-4">
        <h3 className="text-sm font-semibold">Operating constraints</h3>
        <p className="mt-1 text-xs text-muted-foreground">Override private-fleet availability and route limits for this scenario.</p>
        <div className="mt-3 grid gap-3 sm:grid-cols-3">
          <NumberField label="Private vehicles" value={constraints.private_vehicle_limit} onChange={(v) => constraintNumber('private_vehicle_limit', v)} />
          <NumberField label="Max route minutes" value={constraints.max_route_minutes} onChange={(v) => constraintNumber('max_route_minutes', v)} />
          <NumberField label="Max stops / route" value={constraints.max_stops_per_route} onChange={(v) => constraintNumber('max_stops_per_route', v)} />
        </div>
      </section>

      <section className="rounded-lg border border-border bg-card p-4">
        <div className="flex items-center justify-between gap-3">
          <div>
            <h3 className="text-sm font-semibold">Transportation choices</h3>
            <p className="mt-1 text-xs text-muted-foreground">Allow overflow to use a contracted carrier.</p>
          </div>
          <label className="flex items-center gap-2 text-sm"><input type="checkbox" checked={choices.allow_carrier} onChange={(e) => onChoicesChange({ ...choices, allow_carrier: e.target.checked })} /> Carrier fallback</label>
        </div>
        {choices.allow_carrier && (
          <div className="mt-3 grid gap-3 sm:grid-cols-3">
            <TextField label="Carrier" value={choices.carrier_name} onChange={(v) => onChoicesChange({ ...choices, carrier_name: v })} />
            <TextField label="Contract" value={choices.contract_name} onChange={(v) => onChoicesChange({ ...choices, contract_name: v })} />
            <NumberField label="Capacity (stops)" value={choices.carrier_capacity_stops} onChange={(v) => choiceNumber('carrier_capacity_stops', v)} />
            <NumberField label="Rate / mile" value={choices.rate_per_mile} step="0.25" onChange={(v) => choiceNumber('rate_per_mile', v)} />
            <NumberField label="Rate / stop" value={choices.rate_per_stop} step="5" onChange={(v) => choiceNumber('rate_per_stop', v)} />
            <NumberField label="Minimum charge" value={choices.minimum_charge} step="25" onChange={(v) => choiceNumber('minimum_charge', v)} />
            <NumberField label="Fuel surcharge %" value={choices.fuel_surcharge_pct} step="1" onChange={(v) => choiceNumber('fuel_surcharge_pct', v)} />
          </div>
        )}
      </section>
    </div>
  )
}

function NumberField({ label, value, onChange, step = '1' }: { label: string; value: number; onChange: (value: string) => void; step?: string }) {
  return <label className="flex flex-col gap-1 text-xs"><span className="font-medium">{label}</span><input type="number" min="0" step={step} value={value} onChange={(e) => onChange(e.target.value)} className="rounded-md border border-border bg-background px-3 py-2 text-sm" /></label>
}

function TextField({ label, value, onChange }: { label: string; value: string; onChange: (value: string) => void }) {
  return <label className="flex flex-col gap-1 text-xs"><span className="font-medium">{label}</span><input value={value} onChange={(e) => onChange(e.target.value)} className="rounded-md border border-border bg-background px-3 py-2 text-sm" /></label>
}
