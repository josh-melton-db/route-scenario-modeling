import { Link } from 'react-router-dom'
import { CalendarRange, CheckCircle2, ExternalLink, Trash2 } from 'lucide-react'
import type {
  Carrier,
  CarrierContract,
  OperatingConstraints,
  OperatingParameterSet,
  PricingContext,
  RateContractSummary,
  TransportationChoices,
} from '@/api/types'
import { formatCurrency } from '@/lib/format'

interface Props {
  constraints: OperatingConstraints
  choices: TransportationChoices
  pricingContext: PricingContext
  onConstraintsChange: (value: OperatingConstraints) => void
  onChoicesChange: (value: TransportationChoices) => void
  onPricingContextChange: (value: PricingContext) => void
  carriers: Carrier[]
  contracts: CarrierContract[]
  rateContracts: RateContractSummary[]
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
  pricingContext,
  onConstraintsChange,
  onChoicesChange,
  onPricingContextChange,
  carriers,
  contracts,
  rateContracts,
  loading = false,
  parameterSets,
  showOperating,
  showTransportation,
  onRemoveOperating,
  onRemoveTransportation,
}: Props) {
  const constraintNumber = (key: keyof OperatingConstraints, value: string) =>
    onConstraintsChange({ ...constraints, [key]: Number(value) })
  const eligibleContracts = contracts.filter(
    (contract) => contract.carrier_id === choices.carrier_id,
  )
  const selectedContract = eligibleContracts.find(
    (contract) => contract.contract_id === choices.contract_id,
  )
  const effectiveContracts = contracts.filter((contract) => {
    if (!contract.active) return false
    if (
      choices.contract_selection === 'automatic' &&
      choices.eligible_carrier_ids.length > 0 &&
      !choices.eligible_carrier_ids.includes(contract.carrier_id)
    ) {
      return false
    }
    if (contract.effective_start && pricingContext.service_date < contract.effective_start) return false
    if (contract.effective_end && pricingContext.service_date > contract.effective_end) return false
    return true
  })
  const linkedRateBook =
    rateContracts.find((contract) => contract.contract_id === choices.contract_id) ??
    rateContracts.find((rateContract) =>
      effectiveContracts.some(
        (contract) => contract.contract_id === rateContract.contract_id,
      ),
    )

  function selectCarrier(carrierId: string) {
    const firstContract = contracts.find(
      (contract) => contract.carrier_id === carrierId,
    )
    onChoicesChange({
      ...choices,
      carrier_id: carrierId,
      contract_id: firstContract?.contract_id ?? '',
    })
  }

  function toggleEligibleCarrier(carrierId: string) {
    const selected = choices.eligible_carrier_ids.includes(carrierId)
    onChoicesChange({
      ...choices,
      eligible_carrier_ids: selected
        ? choices.eligible_carrier_ids.filter((id) => id !== carrierId)
        : [...choices.eligible_carrier_ids, carrierId],
    })
  }

  function toggleAccessorial(code: string) {
    const selected = choices.accessorial_codes.includes(code)
    onChoicesChange({
      ...choices,
      accessorial_codes: selected
        ? choices.accessorial_codes.filter((value) => value !== code)
        : [...choices.accessorial_codes, code],
    })
  }

  return (
    <div className={`grid gap-4 ${showOperating && showTransportation ? 'xl:grid-cols-2' : ''}`}>
      {showOperating && (
        <section className="rounded-lg border border-border bg-card p-4">
          <div className="flex items-start justify-between gap-3">
            <div>
              <h3 className="text-sm font-semibold">Operating constraints</h3>
              <p className="mt-1 text-xs text-muted-foreground">
                Override private-fleet availability and route limits for this scenario.
              </p>
            </div>
            <RemoveButton onClick={onRemoveOperating} />
          </div>
          <label className="mt-3 flex max-w-sm flex-col gap-1 text-xs">
            <span className="font-medium">Inherited parameter set</span>
            <select
              value={constraints.parameter_set_id}
              onChange={(event) => {
                const selected = parameterSets.find(
                  (item) => item.parameter_set_id === event.target.value,
                )
                onConstraintsChange(
                  selected
                    ? {
                        parameter_set_id: selected.parameter_set_id,
                        private_vehicle_limit: selected.private_vehicle_limit,
                        max_route_minutes: selected.max_route_minutes,
                        max_stops_per_route: selected.max_stops_per_route,
                        allow_overtime: selected.allow_overtime,
                      }
                    : { ...constraints, parameter_set_id: event.target.value },
                )
              }}
              className="rounded-md border border-border bg-background px-3 py-2 text-sm"
            >
              {parameterSets.map((item) => (
                <option key={item.parameter_set_id} value={item.parameter_set_id}>
                  {item.parameter_set_name}
                </option>
              ))}
            </select>
          </label>
          <div className="mt-3 grid gap-3 sm:grid-cols-3">
            <NumberField label="Private vehicles" value={constraints.private_vehicle_limit} onChange={(value) => constraintNumber('private_vehicle_limit', value)} />
            <NumberField label="Max route minutes" value={constraints.max_route_minutes} onChange={(value) => constraintNumber('max_route_minutes', value)} />
            <NumberField label="Max stops / route" value={constraints.max_stops_per_route} onChange={(value) => constraintNumber('max_stops_per_route', value)} />
          </div>
          <label className="mt-3 flex items-center gap-2 text-sm">
            <input
              type="checkbox"
              checked={constraints.allow_overtime}
              onChange={(event) =>
                onConstraintsChange({ ...constraints, allow_overtime: event.target.checked })
              }
            />
            Allow private-fleet overtime
          </label>
        </section>
      )}

      {showTransportation && (
        <section className="rounded-lg border border-border bg-card p-4">
          <div className="flex items-start justify-between gap-3">
            <div>
              <h3 className="text-sm font-semibold">Carrier sourcing & contracts</h3>
              <p className="mt-1 text-xs text-muted-foreground">
                Qualify published contracts by service date, lane, and available capacity.
              </p>
            </div>
            <RemoveButton onClick={onRemoveTransportation} />
          </div>

          <div className="mt-4 grid gap-3 sm:grid-cols-3">
            <label className="flex flex-col gap-1 text-xs">
              <span className="font-medium">Service date</span>
              <input
                type="date"
                value={pricingContext.service_date}
                onChange={(event) =>
                  onPricingContextChange({ ...pricingContext, service_date: event.target.value })
                }
                className="rounded-md border border-border bg-background px-3 py-2 text-sm"
              />
            </label>
            <label className="flex flex-col gap-1 text-xs">
              <span className="font-medium">Planning horizon ends</span>
              <input
                type="date"
                min={pricingContext.service_date}
                value={pricingContext.horizon_end}
                onChange={(event) =>
                  onPricingContextChange({ ...pricingContext, horizon_end: event.target.value })
                }
                className="rounded-md border border-border bg-background px-3 py-2 text-sm"
              />
            </label>
            <NumberField
              label="Projected period stops"
              value={pricingContext.projected_period_stops}
              onChange={(value) =>
                onPricingContextChange({
                  ...pricingContext,
                  projected_period_stops: Number(value),
                })
              }
            />
          </div>

          <div className="mt-4 grid gap-3 sm:grid-cols-2">
            <label className="flex flex-col gap-1 text-xs">
              <span className="font-medium">Sourcing policy</span>
              <select
                value={choices.contract_selection}
                onChange={(event) =>
                  onChoicesChange({
                    ...choices,
                    contract_selection: event.target.value as TransportationChoices['contract_selection'],
                  })
                }
                className="rounded-md border border-border bg-background px-3 py-2 text-sm"
              >
                <option value="automatic">Lowest eligible published quote</option>
                <option value="locked">Lock one carrier contract</option>
              </select>
            </label>
            <label className="flex flex-col gap-1 text-xs">
              <span className="font-medium">Commitment policy</span>
              <select
                value={choices.commitment_policy}
                onChange={(event) =>
                  onChoicesChange({
                    ...choices,
                    commitment_policy: event.target.value as TransportationChoices['commitment_policy'],
                  })
                }
                className="rounded-md border border-border bg-background px-3 py-2 text-sm"
              >
                <option value="honor">Honor capacity commitments</option>
                <option value="ignore">Ignore commitments for this what-if</option>
              </select>
            </label>
          </div>

          <div className="mt-4 flex flex-wrap items-center gap-4 text-sm">
            <label className="flex items-center gap-2">
              <input
                type="checkbox"
                checked={choices.allow_private_fleet}
                onChange={(event) =>
                  onChoicesChange({ ...choices, allow_private_fleet: event.target.checked })
                }
              />
              Allow private fleet
            </label>
            <label className="flex items-center gap-2">
              <input
                type="checkbox"
                checked={choices.allow_carrier}
                onChange={(event) =>
                  onChoicesChange({ ...choices, allow_carrier: event.target.checked })
                }
              />
              Allow carrier capacity
            </label>
          </div>

          {choices.allow_carrier && choices.contract_selection === 'automatic' && (
            <div className="mt-4">
              <div className="text-xs font-medium">Eligible carrier pool</div>
              <div className="mt-2 flex flex-wrap gap-2">
                {carriers.map((carrier) => {
                  const selected = choices.eligible_carrier_ids.includes(carrier.carrier_id)
                  return (
                    <label
                      key={carrier.carrier_id}
                      className={`flex cursor-pointer items-center gap-2 rounded-md border px-3 py-2 text-xs ${selected ? 'border-primary/50 bg-primary/10 text-foreground' : 'border-border text-muted-foreground'}`}
                    >
                      <input
                        type="checkbox"
                        checked={selected}
                        onChange={() => toggleEligibleCarrier(carrier.carrier_id)}
                      />
                      {carrier.carrier_name}
                    </label>
                  )
                })}
              </div>
            </div>
          )}

          {choices.allow_carrier && choices.contract_selection === 'locked' && (
            <div className="mt-4 grid gap-3 sm:grid-cols-2">
              <label className="flex flex-col gap-1 text-xs">
                <span className="font-medium">Carrier</span>
                <select
                  disabled={loading || carriers.length === 0}
                  value={choices.carrier_id}
                  onChange={(event) => selectCarrier(event.target.value)}
                  className="rounded-md border border-border bg-background px-3 py-2 text-sm"
                >
                  <option value="">Select a carrier</option>
                  {carriers.map((carrier) => (
                    <option key={carrier.carrier_id} value={carrier.carrier_id}>
                      {carrier.carrier_name}
                    </option>
                  ))}
                </select>
              </label>
              <label className="flex flex-col gap-1 text-xs">
                <span className="font-medium">Contract</span>
                <select
                  disabled={loading || eligibleContracts.length === 0}
                  value={choices.contract_id}
                  onChange={(event) =>
                    onChoicesChange({ ...choices, contract_id: event.target.value })
                  }
                  className="rounded-md border border-border bg-background px-3 py-2 text-sm"
                >
                  <option value="">Select a contract</option>
                  {eligibleContracts.map((contract) => (
                    <option key={contract.contract_id} value={contract.contract_id}>
                      {contract.contract_name}
                    </option>
                  ))}
                </select>
              </label>
            </div>
          )}

          {choices.allow_carrier && (
            <div className="mt-4">
              <div className="text-xs font-medium">Scenario accessorials</div>
              <div className="mt-2 flex flex-wrap gap-3 text-xs text-muted-foreground">
                {[
                  ['LIFTGATE', 'Liftgate'],
                  ['INSIDE_DELIVERY', 'Inside delivery'],
                  ['DETENTION', 'Detention'],
                ].map(([code, label]) => (
                  <label key={code} className="flex items-center gap-2">
                    <input
                      type="checkbox"
                      checked={choices.accessorial_codes.includes(code)}
                      onChange={() => toggleAccessorial(code)}
                    />
                    {label}
                  </label>
                ))}
              </div>
            </div>
          )}

          {choices.allow_carrier && (
            <div className="mt-4 flex flex-wrap items-center justify-between gap-3 rounded-md border border-primary/25 bg-primary/5 p-3 text-xs">
              <div className="flex items-start gap-2">
                {effectiveContracts.length > 0 ? (
                  <CheckCircle2 className="mt-0.5 h-4 w-4 text-primary" />
                ) : (
                  <CalendarRange className="mt-0.5 h-4 w-4 text-destructive" />
                )}
                <div>
                  <div className="font-medium text-foreground">
                    {effectiveContracts.length} effective contract{effectiveContracts.length === 1 ? '' : 's'}
                  </div>
                  <div className="mt-1 text-muted-foreground">
                    Resolved for {pricingContext.service_date}; lane and capacity are validated during precheck.
                  </div>
                </div>
              </div>
              {linkedRateBook && (
                <Link
                  to={`/rates/contracts/${encodeURIComponent(linkedRateBook.contract_id)}/versions/${encodeURIComponent(linkedRateBook.version.version_id)}/overview`}
                  className="inline-flex items-center gap-1 font-medium text-primary hover:underline"
                >
                  Inspect rate book <ExternalLink className="h-3.5 w-3.5" />
                </Link>
              )}
            </div>
          )}

          {selectedContract && choices.contract_selection === 'locked' && (
            <dl className="mt-3 grid grid-cols-2 gap-x-4 gap-y-2 rounded-md border border-border/60 bg-background/40 p-3 text-xs sm:grid-cols-3">
              <ContractValue label="Capacity" value={`${selectedContract.capacity_stops} stops`} />
              <ContractValue label="Rate / mile" value={formatCurrency(selectedContract.rate_per_mile)} />
              <ContractValue label="Rate / stop" value={formatCurrency(selectedContract.rate_per_stop)} />
              <ContractValue label="Minimum" value={formatCurrency(selectedContract.minimum_charge)} />
              <ContractValue label="Fuel surcharge" value={`${selectedContract.fuel_surcharge_pct}%`} />
              <ContractValue label="Effective" value={`${selectedContract.effective_start ?? 'Open'} – ${selectedContract.effective_end ?? 'Open'}`} />
            </dl>
          )}
        </section>
      )}
    </div>
  )
}

function RemoveButton({ onClick }: { onClick: () => void }) {
  return (
    <button
      type="button"
      onClick={onClick}
      className="inline-flex items-center gap-1 rounded-md border border-border px-2 py-1 text-xs text-muted-foreground hover:text-destructive"
    >
      <Trash2 className="h-3.5 w-3.5" />
      Remove
    </button>
  )
}

function NumberField({
  label,
  value,
  onChange,
  step = '1',
}: {
  label: string
  value: number
  onChange: (value: string) => void
  step?: string
}) {
  return (
    <label className="flex flex-col gap-1 text-xs">
      <span className="font-medium">{label}</span>
      <input
        type="number"
        min="0"
        step={step}
        value={value}
        onChange={(event) => onChange(event.target.value)}
        className="rounded-md border border-border bg-background px-3 py-2 text-sm"
      />
    </label>
  )
}

function ContractValue({ label, value }: { label: string; value: string }) {
  return (
    <div>
      <dt className="text-muted-foreground">{label}</dt>
      <dd className="mt-0.5 font-medium tabular-nums">{value}</dd>
    </div>
  )
}
