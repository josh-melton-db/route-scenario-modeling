import { Trash2 } from 'lucide-react'
import type { Carrier, CarrierContract, OperatingConstraints, OperatingParameterSet, TransportationChoices } from '@/api/types'
import { formatCurrency } from '@/lib/format'

interface Props {
  constraints: OperatingConstraints
  choices: TransportationChoices
  onConstraintsChange: (value: OperatingConstraints) => void
  onChoicesChange: (value: TransportationChoices) => void
  carriers: Carrier[]
  contracts: CarrierContract[]
  loading?: boolean
  parameterSets: OperatingParameterSet[]
  showOperating: boolean
  showTransportation: boolean
  onRemoveOperating: () => void
  onRemoveTransportation: () => void
}

export default function TransportationOptionsPanel({
  constraints,
  choices,
  onConstraintsChange,
  onChoicesChange,
  carriers,
  contracts,
  loading = false,
  parameterSets,
  showOperating,
  showTransportation,
  onRemoveOperating,
  onRemoveTransportation,
}: Props) {
  const constraintNumber = (key: keyof OperatingConstraints, value: string) =>
    onConstraintsChange({ ...constraints, [key]: Number(value) })
  const eligibleContracts = contracts.filter((contract) => contract.carrier_id === choices.carrier_id)
  const selectedContract = eligibleContracts.find((contract) => contract.contract_id === choices.contract_id)

  function selectCarrier(carrierId: string) {
    const firstContract = contracts.find((contract) => contract.carrier_id === carrierId)
    onChoicesChange({ ...choices, carrier_id: carrierId, contract_id: firstContract?.contract_id ?? '' })
  }

  return (
    <div className={`grid gap-4 ${showOperating && showTransportation ? 'xl:grid-cols-2' : ''}`}>
      {showOperating && <section className="rounded-lg border border-border bg-card p-4">
        <div className="flex items-start justify-between gap-3"><div><h3 className="text-sm font-semibold">Operating constraints</h3>
        <p className="mt-1 text-xs text-muted-foreground">Override private-fleet availability and route limits for this scenario.</p>
        </div><RemoveButton onClick={onRemoveOperating} /></div>
        <label className="mt-3 flex max-w-sm flex-col gap-1 text-xs"><span className="font-medium">Inherited parameter set</span><select value={constraints.parameter_set_id} onChange={(e) => {
          const selected = parameterSets.find((item) => item.parameter_set_id === e.target.value)
          onConstraintsChange(selected ? { parameter_set_id: selected.parameter_set_id, private_vehicle_limit: selected.private_vehicle_limit, max_route_minutes: selected.max_route_minutes, max_stops_per_route: selected.max_stops_per_route, allow_overtime: selected.allow_overtime } : { ...constraints, parameter_set_id: e.target.value })
        }} className="rounded-md border border-border bg-background px-3 py-2 text-sm">{parameterSets.map((item) => <option key={item.parameter_set_id} value={item.parameter_set_id}>{item.parameter_set_name}</option>)}</select></label>
        <div className="mt-3 grid gap-3 sm:grid-cols-3">
          <NumberField label="Private vehicles" value={constraints.private_vehicle_limit} onChange={(v) => constraintNumber('private_vehicle_limit', v)} />
          <NumberField label="Max route minutes" value={constraints.max_route_minutes} onChange={(v) => constraintNumber('max_route_minutes', v)} />
          <NumberField label="Max stops / route" value={constraints.max_stops_per_route} onChange={(v) => constraintNumber('max_stops_per_route', v)} />
        </div>
        <label className="mt-3 flex items-center gap-2 text-sm"><input type="checkbox" checked={constraints.allow_overtime} onChange={(e) => onConstraintsChange({ ...constraints, allow_overtime: e.target.checked })} />Allow private-fleet overtime</label>
      </section>}

      {showTransportation && <section className="rounded-lg border border-border bg-card p-4">
        <div className="flex items-center justify-between gap-3">
          <div>
            <h3 className="text-sm font-semibold">Transportation choices</h3>
            <p className="mt-1 text-xs text-muted-foreground">Allow overflow to use a contracted carrier.</p>
          </div>
          <div className="flex items-center gap-3"><label className="flex items-center gap-2 text-sm"><input type="checkbox" checked={choices.allow_carrier} onChange={(e) => onChoicesChange({ ...choices, allow_carrier: e.target.checked })} /> Carrier fallback</label><RemoveButton onClick={onRemoveTransportation} /></div>
        </div>
        {choices.allow_carrier && (
          <div className="mt-3">
            <div className="grid gap-3 sm:grid-cols-2">
              <label className="flex flex-col gap-1 text-xs"><span className="font-medium">Carrier</span><select disabled={loading || carriers.length === 0} value={choices.carrier_id} onChange={(e) => selectCarrier(e.target.value)} className="rounded-md border border-border bg-background px-3 py-2 text-sm"><option value="">Select a carrier</option>{carriers.map((carrier) => <option key={carrier.carrier_id} value={carrier.carrier_id}>{carrier.carrier_name}</option>)}</select></label>
              <label className="flex flex-col gap-1 text-xs"><span className="font-medium">Contract</span><select disabled={loading || eligibleContracts.length === 0} value={choices.contract_id} onChange={(e) => onChoicesChange({ ...choices, contract_id: e.target.value })} className="rounded-md border border-border bg-background px-3 py-2 text-sm"><option value="">Select a contract</option>{eligibleContracts.map((contract) => <option key={contract.contract_id} value={contract.contract_id}>{contract.contract_name}</option>)}</select></label>
            </div>
            {selectedContract ? (
              <dl className="mt-3 grid grid-cols-2 gap-x-4 gap-y-2 rounded-md border border-border/60 bg-background/40 p-3 text-xs sm:grid-cols-3">
                <ContractValue label="Capacity" value={`${selectedContract.capacity_stops} stops`} />
                <ContractValue label="Rate / mile" value={formatCurrency(selectedContract.rate_per_mile)} />
                <ContractValue label="Rate / stop" value={formatCurrency(selectedContract.rate_per_stop)} />
                <ContractValue label="Minimum" value={formatCurrency(selectedContract.minimum_charge)} />
                <ContractValue label="Fuel surcharge" value={`${selectedContract.fuel_surcharge_pct}%`} />
                <ContractValue label="Effective" value={`${selectedContract.effective_start ?? 'Open'} – ${selectedContract.effective_end ?? 'Open'}`} />
              </dl>
            ) : <p className="mt-3 text-xs text-muted-foreground">{loading ? 'Loading carrier contracts…' : 'No active contract is available for this carrier. Add one in the Data editor.'}</p>}
          </div>
        )}
      </section>}
    </div>
  )
}

function RemoveButton({ onClick }: { onClick: () => void }) {
  return <button type="button" onClick={onClick} className="inline-flex items-center gap-1 rounded-md border border-border px-2 py-1 text-xs text-muted-foreground hover:text-destructive"><Trash2 className="h-3.5 w-3.5" />Remove</button>
}

function NumberField({ label, value, onChange, step = '1' }: { label: string; value: number; onChange: (value: string) => void; step?: string }) {
  return <label className="flex flex-col gap-1 text-xs"><span className="font-medium">{label}</span><input type="number" min="0" step={step} value={value} onChange={(e) => onChange(e.target.value)} className="rounded-md border border-border bg-background px-3 py-2 text-sm" /></label>
}

function ContractValue({ label, value }: { label: string; value: string }) {
  return <div><dt className="text-muted-foreground">{label}</dt><dd className="mt-0.5 font-medium tabular-nums">{value}</dd></div>
}
