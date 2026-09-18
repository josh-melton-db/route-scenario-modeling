import { useEffect, useState } from 'react'
import type { FormEvent, MouseEvent, ReactNode } from 'react'
import { Link, NavLink, Navigate, useNavigate, useParams, useSearchParams } from 'react-router-dom'
import {
  AlertTriangle,
  ArrowLeft,
  CalendarRange,
  CheckCircle2,
  CopyPlus,
  FileClock,
  Fuel,
  Gauge,
  Loader2,
  MapPinned,
  Pencil,
  Plus,
  ReceiptText,
  Save,
  Send,
  ShieldCheck,
  Trash2,
  X,
} from 'lucide-react'
import ErrorState from '@/components/ErrorState'
import RateQuoteTester from '@/components/RateQuoteTester'
import {
  useCreateRateVersion,
  useDepots,
  useDiscardRateDraft,
  usePublishRateDraft,
  useRateAuthoringOptions,
  useRateContractDetail,
  useSaveRateDraft,
  useValidateRateDraft,
} from '@/api/queries'
import type {
  AccessorialRule,
  CapacityCommitmentRule,
  Depot,
  FuelSurchargeRule,
  LaneRateRule,
  RateContractDetail,
  RateAccessorialTemplate,
  RateDraftUpdateRequest,
  RateValidationResponse,
  RateVersionCreateRequest,
  VolumeTierRule,
} from '@/api/types'
import { formatCurrency, formatNumber, formatPercent } from '@/lib/format'
import { cn } from '@/lib/utils'

const tabs = [
  { id: 'overview', label: 'Overview' },
  { id: 'lane-rates', label: 'Lane rates' },
  { id: 'fuel-surcharges', label: 'Fuel surcharges' },
  { id: 'accessorials', label: 'Accessorials' },
  { id: 'volume-tiers', label: 'Volume tiers' },
  { id: 'capacity-commitments', label: 'Capacity commitments' },
  { id: 'test-quote', label: 'Test quote' },
  { id: 'version-history', label: 'Version history' },
] as const

type Detail = RateContractDetail

export default function ContractDetailPage() {
  const { contractId = '', versionId = '', tab = 'overview' } = useParams()
  const navigate = useNavigate()
  const [searchParams] = useSearchParams()
  const contract = useRateContractDetail(contractId, versionId)
  const saveDraft = useSaveRateDraft()
  const validateDraft = useValidateRateDraft()
  const publishDraft = usePublishRateDraft()
  const discardDraft = useDiscardRateDraft()
  const createVersion = useCreateRateVersion()
  const depots = useDepots()
  const authoringOptions = useRateAuthoringOptions()
  const [draft, setDraft] = useState<Detail | null>(null)
  const [dirty, setDirty] = useState(false)
  const [validation, setValidation] = useState<RateValidationResponse | null>(null)
  const [showCreateVersion, setShowCreateVersion] = useState(searchParams.get('createVersion') === '1')
  const basePath = `/rates/contracts/${encodeURIComponent(contractId)}/versions/${encodeURIComponent(versionId)}`

  useEffect(() => {
    if (
      contract.data
      && (!draft || draft.version.version_id !== contract.data.version.version_id || !dirty)
      && draft !== contract.data
    ) {
      setDraft(contract.data)
      setDirty(false)
      setValidation(null)
    }
  }, [contract.data, dirty, draft])

  useEffect(() => {
    if (!dirty) return
    const warn = (event: BeforeUnloadEvent) => event.preventDefault()
    window.addEventListener('beforeunload', warn)
    return () => window.removeEventListener('beforeunload', warn)
  }, [dirty])

  if (!tabs.some((item) => item.id === tab)) return <Navigate to={`${basePath}/overview`} replace />
  if (contract.error) return <ErrorState title="Could not load contract" error={contract.error} />
  if (contract.isLoading || !contract.data || !draft) return <DetailSkeleton />
  const detail = draft
  const isDraft = detail.version.status === 'draft'
  const busy = saveDraft.isPending || validateDraft.isPending || publishDraft.isPending || discardDraft.isPending
  const actionError = saveDraft.error ?? validateDraft.error ?? publishDraft.error ?? discardDraft.error

  function update(next: Detail) {
    setDraft(next)
    setDirty(true)
    setValidation(null)
  }

  function payload(current = detail): RateDraftUpdateRequest {
    return {
      contract_name: current.contract_name,
      currency: current.version.currency,
      effective_start: current.version.effective_start ?? '',
      effective_end: current.version.effective_end ?? '',
      change_reason: current.version.change_reason ?? '',
      lane_rates: current.lane_rates,
      fuel_surcharges: current.fuel_surcharges,
      accessorials: current.accessorials,
      volume_tiers: current.volume_tiers,
      capacity_commitments: current.capacity_commitments,
    }
  }

  async function persistDraft() {
    if (!dirty) return detail
    const saved = await saveDraft.mutateAsync({ contractId, versionId, payload: payload() })
    setDraft(saved)
    setDirty(false)
    return saved
  }

  async function runValidation() {
    await persistDraft()
    const result = await validateDraft.mutateAsync({ contractId, versionId })
    setValidation(result)
    return result
  }

  async function publish() {
    const result = await runValidation()
    if (!result.valid) return
    if (!window.confirm(`Publish Version ${detail.version.version_number}? Published rates become immutable.`)) return
    const published = await publishDraft.mutateAsync({ contractId, versionId, payload: { published_by: 'Rate manager' } })
    setDraft(published)
    setDirty(false)
    setValidation(null)
  }

  async function discard() {
    if (!window.confirm(`Discard Draft Version ${detail.version.version_number}? This cannot be undone.`)) return
    await discardDraft.mutateAsync({ contractId, versionId })
    const prior = detail.version_history.find((version) => version.status !== 'draft' && version.version_id !== versionId)
    navigate(prior ? `/rates/contracts/${encodeURIComponent(contractId)}/versions/${encodeURIComponent(prior.version_id)}/overview` : '/rates')
  }

  function back(event: MouseEvent<HTMLAnchorElement>) {
    if (dirty && !window.confirm('Leave this draft without saving your changes?')) event.preventDefault()
  }

  return (
    <div className="flex flex-col gap-5 px-4 py-5 sm:px-6 lg:px-8">
      <header>
        <Link to="/rates" onClick={back} className="inline-flex items-center gap-1 text-xs text-muted-foreground hover:text-foreground"><ArrowLeft className="h-3.5 w-3.5" />Rates</Link>
        <div className="mt-3 flex flex-wrap items-start justify-between gap-4">
          <div>
            <div className="flex flex-wrap items-center gap-2"><h1 className="text-2xl font-semibold tracking-tight">{detail.contract_name}</h1><StatusPill status={detail.version.status} />{dirty ? <span className="text-xs font-medium text-amber-400">Unsaved changes</span> : null}</div>
            <p className="mt-1 text-sm text-muted-foreground">{detail.carrier_name} · {detail.contract_id} · Version {detail.version.version_number}</p>
          </div>
          {!isDraft ? <button type="button" onClick={() => setShowCreateVersion(true)} className="inline-flex items-center gap-2 rounded-md bg-primary px-3 py-2 text-sm font-semibold text-primary-foreground"><Pencil className="h-4 w-4" />Create new version</button> : <div className="text-right text-xs text-muted-foreground"><div>{formatRange(detail.version.effective_start, detail.version.effective_end)}</div><div className="mt-1">{detail.source} · saved {new Date(detail.freshness_at).toLocaleString()}</div></div>}
        </div>
      </header>

      {isDraft ? <DraftWorkspace detail={detail} dirty={dirty} busy={busy} onChange={update} onSave={() => void persistDraft()} onValidate={() => void runValidation()} onPublish={() => void publish()} onDiscard={() => void discard()} /> : null}
      {actionError ? <div className="rounded-md border border-destructive/40 bg-destructive/10 p-3 text-xs text-destructive">{friendlyError(actionError)}</div> : null}
      {validation ? <ValidationPanel validation={validation} basePath={basePath} /> : null}

      <nav aria-label="Contract sections" className="overflow-x-auto border-b border-border">
        <div className="flex min-w-max gap-1">
          {tabs.map((item) => <NavLink key={item.id} to={`${basePath}/${item.id}`} className={({ isActive }) => cn('border-b-2 px-3 py-2.5 text-sm font-medium transition-colors', isActive ? 'border-primary text-foreground' : 'border-transparent text-muted-foreground hover:text-foreground')}>{item.label}</NavLink>)}
        </div>
      </nav>

      {tab === 'overview' && <Overview detail={detail} />}
      {tab === 'lane-rates' && (isDraft ? <LaneRatesEditor detail={detail} depots={depots.data ?? []} destinations={authoringOptions.data?.destinations ?? []} onChange={update} /> : <LaneRates detail={detail} />)}
      {tab === 'fuel-surcharges' && (isDraft ? <FuelEditor detail={detail} onChange={update} /> : <FuelSurcharges detail={detail} />)}
      {tab === 'accessorials' && (isDraft ? <AccessorialEditor detail={detail} templates={authoringOptions.data?.accessorials ?? []} onChange={update} /> : <Accessorials detail={detail} />)}
      {tab === 'volume-tiers' && (isDraft ? <TierEditor detail={detail} onChange={update} /> : <VolumeTiers detail={detail} />)}
      {tab === 'capacity-commitments' && (isDraft ? <CommitmentEditor detail={detail} onChange={update} /> : <Commitments detail={detail} />)}
      {tab === 'test-quote' && (isDraft && dirty ? <SaveBeforeTesting onSave={() => void persistDraft()} pending={saveDraft.isPending} /> : <RateQuoteTester contract={detail} />)}
      {tab === 'version-history' && <VersionHistory detail={detail} />}
      {showCreateVersion ? <CreateVersionDialog detail={detail} pending={createVersion.isPending} error={createVersion.error} onClose={() => { if (!createVersion.isPending) setShowCreateVersion(false) }} onSubmit={(request) => createVersion.mutate({ contractId, payload: request }, { onSuccess: (created) => { setShowCreateVersion(false); navigate(`/rates/contracts/${encodeURIComponent(contractId)}/versions/${encodeURIComponent(created.version.version_id)}/lane-rates`) } })} /> : null}
    </div>
  )
}

function DraftWorkspace({ detail, dirty, busy, onChange, onSave, onValidate, onPublish, onDiscard }: { detail: Detail; dirty: boolean; busy: boolean; onChange: (detail: Detail) => void; onSave: () => void; onValidate: () => void; onPublish: () => void; onDiscard: () => void }) {
  function versionChange(changes: Partial<Detail['version']>) {
    onChange({ ...detail, version: { ...detail.version, ...changes } })
  }
  return <section className="rounded-lg border border-amber-400/30 bg-amber-400/[0.04]"><div className="grid gap-3 p-4 lg:grid-cols-[1.3fr_160px_160px_110px_1.5fr]"><EditorField label="Contract name"><input aria-label="Draft contract name" value={detail.contract_name} onChange={(event) => onChange({ ...detail, contract_name: event.target.value })} className="input w-full" /></EditorField><EditorField label="Effective start"><input aria-label="Draft effective start" type="date" value={detail.version.effective_start ?? ''} onChange={(event) => versionChange({ effective_start: event.target.value })} className="input w-full" /></EditorField><EditorField label="Effective end"><input aria-label="Draft effective end" type="date" min={detail.version.effective_start ?? undefined} value={detail.version.effective_end ?? ''} onChange={(event) => versionChange({ effective_end: event.target.value })} className="input w-full" /></EditorField><EditorField label="Currency"><select aria-label="Draft currency" value={detail.version.currency} onChange={(event) => versionChange({ currency: event.target.value })} className="input w-full"><option>USD</option><option>CAD</option><option>MXN</option></select></EditorField><EditorField label="Change summary"><input aria-label="Draft change summary" value={detail.version.change_reason ?? ''} onChange={(event) => versionChange({ change_reason: event.target.value })} placeholder="What changed and why?" className="input w-full" /></EditorField></div><div className="flex flex-wrap items-center justify-between gap-3 border-t border-amber-400/20 px-4 py-3"><div className="text-xs text-muted-foreground">Changes across all five tabs publish together as Version {detail.version.version_number}.</div><div className="flex flex-wrap gap-2"><button type="button" onClick={onDiscard} disabled={busy} className="inline-flex items-center gap-1.5 rounded-md border border-destructive/40 px-3 py-2 text-xs font-medium text-destructive disabled:opacity-50"><Trash2 className="h-3.5 w-3.5" />Discard</button><button type="button" onClick={onSave} disabled={busy || !dirty} className="inline-flex items-center gap-1.5 rounded-md border border-border px-3 py-2 text-xs font-medium disabled:opacity-50">{busy && dirty ? <Loader2 className="h-3.5 w-3.5 animate-spin" /> : <Save className="h-3.5 w-3.5" />}Save draft</button><button type="button" onClick={onValidate} disabled={busy} className="inline-flex items-center gap-1.5 rounded-md border border-primary/40 px-3 py-2 text-xs font-medium text-primary disabled:opacity-50"><CheckCircle2 className="h-3.5 w-3.5" />Validate</button><button type="button" onClick={onPublish} disabled={busy} className="inline-flex items-center gap-1.5 rounded-md bg-primary px-3 py-2 text-xs font-semibold text-primary-foreground disabled:opacity-50">{busy ? <Loader2 className="h-3.5 w-3.5 animate-spin" /> : <Send className="h-3.5 w-3.5" />}Publish</button></div></div></section>
}

function ValidationPanel({ validation, basePath }: { validation: RateValidationResponse; basePath: string }) {
  const errors = validation.issues.filter((issue) => issue.severity === 'error')
  const tabFor = (field: string) => field.startsWith('lane_rates') ? 'lane-rates' : field.startsWith('fuel_surcharges') ? 'fuel-surcharges' : field.startsWith('accessorials') ? 'accessorials' : field.startsWith('volume_tiers') ? 'volume-tiers' : field.startsWith('capacity_commitments') ? 'capacity-commitments' : 'overview'
  return <section className={cn('rounded-lg border p-4', validation.valid ? 'border-primary/35 bg-primary/5' : 'border-destructive/35 bg-destructive/5')}><div className="flex items-start gap-2">{validation.valid ? <CheckCircle2 className="mt-0.5 h-5 w-5 text-primary" /> : <AlertTriangle className="mt-0.5 h-5 w-5 text-destructive" />}<div className="min-w-0 flex-1"><div className="text-sm font-semibold">{validation.summary}</div>{validation.issues.length ? <div className="mt-3 grid gap-2 sm:grid-cols-2">{validation.issues.map((issue, index) => <Link key={`${issue.code}-${issue.field}-${index}`} to={`${basePath}/${tabFor(issue.field)}`} className="rounded-md border border-border/70 bg-background/40 p-3 text-xs hover:border-primary/40"><div className={cn('font-medium', issue.severity === 'error' ? 'text-destructive' : 'text-amber-400')}>{issue.severity === 'error' ? 'Error' : 'Warning'} · {issue.field}</div><div className="mt-1 text-muted-foreground">{issue.message}</div></Link>)}</div> : null}{validation.valid && !errors.length ? <p className="mt-2 text-xs text-muted-foreground">Publishing will lock this version and make it available for effective-date resolution.</p> : null}</div></div></section>
}

function Overview({ detail }: { detail: Detail }) {
  const commitment = detail.capacity_commitments[0]
  return <div className="grid gap-4 lg:grid-cols-[1fr_340px]"><section className="rounded-lg border border-border bg-card p-4"><h2 className="text-sm font-semibold">Contract scope</h2><div className="mt-4 grid gap-4 sm:grid-cols-2 xl:grid-cols-3"><OverviewValue icon={MapPinned} label="Lane rules" value={`${detail.lane_rates.length} defined`} /><OverviewValue icon={Fuel} label="Fuel schedules" value={`${detail.fuel_surcharges.length} defined`} /><OverviewValue icon={ReceiptText} label="Accessorials" value={`${detail.accessorials.length} typed charges`} /><OverviewValue icon={Gauge} label="Volume tiers" value={`${detail.volume_tiers.length} bands`} /><OverviewValue icon={ShieldCheck} label="Currency" value={detail.version.currency} /><OverviewValue icon={CalendarRange} label="Effective dates" value={formatRange(detail.version.effective_start, detail.version.effective_end)} /></div><div className="mt-5 rounded-md border border-border/60 bg-background/35 p-3 text-xs leading-5 text-muted-foreground">Quotes pin the contract version and every applied rule ID. Later versions never re-price historical scenarios.</div></section><section className="rounded-lg border border-border bg-card p-4"><h2 className="text-sm font-semibold">Capacity commitment</h2>{commitment ? <><div className="mt-4 flex items-end justify-between"><div><div className="text-2xl font-semibold tabular-nums">{formatNumber(commitment.current_utilization)} / {formatNumber(commitment.committed_quantity)}</div><div className="mt-1 text-xs text-muted-foreground">{commitment.unit} used · {commitment.period}</div></div><div className="text-right text-xs text-muted-foreground">Max {formatNumber(commitment.capacity_quantity)}</div></div><Progress value={commitment.current_utilization} max={commitment.capacity_quantity} /><div className="mt-3 grid grid-cols-2 gap-3 text-xs"><MetaBox label="Shortfall rate" value={`${formatCurrency(commitment.shortfall_rate)} / unit`} /><MetaBox label="Overage rate" value={`${formatCurrency(commitment.overage_rate)} / unit`} /></div></> : <Empty label="No capacity commitment is defined." />}</section></div>
}

function LaneRatesEditor({ detail, depots, destinations, onChange }: EditorProps & { depots: Depot[]; destinations: string[] }) {
  const originOptions = unique([
    ...depots.map((depot) => depot.depot_id),
    ...detail.lane_rates.map((rule) => rule.origin).filter(Boolean),
    '*',
  ])
  const destinationOptions = unique([
    ...destinations,
    ...detail.lane_rates.map((rule) => rule.destination).filter(Boolean),
    '*',
  ])
  const updateRule = (index: number, changes: Partial<LaneRateRule>) => onChange({
    ...detail,
    lane_rates: detail.lane_rates.map((row, current) => current === index ? { ...row, ...changes } : row),
  })

  function add() {
    const origin = originOptions.find((value) => value !== '*') ?? '*'
    const destination = destinationOptions.find((value) => value !== '*') ?? '*'
    const source = [...detail.lane_rates].sort((left, right) => {
      const leftSpecificity = Number(left.origin !== '*') + Number(left.destination !== '*')
      const rightSpecificity = Number(right.origin !== '*') + Number(right.destination !== '*')
      return rightSpecificity - leftSpecificity || right.priority - left.priority
    })[0]
    onChange({
      ...detail,
      lane_rates: [
        ...detail.lane_rates,
        {
          rule_id: ruleId(detail, 'LANE'),
          lane_name: derivedLaneName(origin, destination, depots),
          origin,
          destination,
          priority: source?.priority ?? 100,
          flat_rate: source?.flat_rate ?? 75,
          rate_per_mile: source?.rate_per_mile ?? 4.5,
          rate_per_stop: source?.rate_per_stop ?? 45,
          included_stops: source?.included_stops ?? 1,
          minimum_charge: source?.minimum_charge ?? 350,
          mileage_rounding: source?.mileage_rounding ?? 'up_to_mile',
        },
      ],
    })
  }

  function changeCoverage(index: number, rule: LaneRateRule, field: 'origin' | 'destination', value: string) {
    const origin = field === 'origin' ? value : rule.origin
    const destination = field === 'destination' ? value : rule.destination
    updateRule(index, {
      [field]: value,
      lane_name: derivedLaneName(origin, destination, depots),
    })
  }

  return <EditorSection title="Lane rates" description="Choose governed depots and destination zones. Commercial terms start from the closest existing lane and remain editable." icon={MapPinned} onAdd={add} addLabel="Add lane"><EditorTable headers={['Lane and coverage', 'Priority', 'Lane base', 'Per mile', 'Per stop', 'Included', 'Minimum', 'Mileage', '']} minWidth="1180px">{detail.lane_rates.map((rule, index) => <tr key={rule.rule_id} className="border-t border-border/60"><td className="p-3"><div className="text-sm font-medium">{derivedLaneName(rule.origin, rule.destination, depots)}</div><div className="mt-1 text-[10px] text-muted-foreground">Auto-filled from coverage</div><div className="mt-2 flex items-center gap-1"><select aria-label={`Lane ${index + 1} origin depot`} value={rule.origin} onChange={(event) => changeCoverage(index, rule, 'origin', event.target.value)} className="input w-44">{originOptions.map((origin) => { const depot = depots.find((row) => row.depot_id === origin); return <option key={origin} value={origin}>{origin === '*' ? 'Any origin (fallback)' : depot ? `${depot.name} · ${depot.depot_id}` : origin}</option> })}</select><span>→</span><select aria-label={`Lane ${index + 1} destination zone`} value={rule.destination} onChange={(event) => changeCoverage(index, rule, 'destination', event.target.value)} className="input w-48">{destinationOptions.map((destination) => <option key={destination} value={destination}>{destination === '*' ? 'Any destination (fallback)' : destination}</option>)}</select></div><RuleId value={rule.rule_id} /></td><NumberCell label={`Lane ${index + 1} priority`} value={rule.priority} onChange={(value) => updateRule(index, { priority: value })} step="1" /><NumberCell label={`Lane ${index + 1} base rate`} value={rule.flat_rate} onChange={(value) => updateRule(index, { flat_rate: value })} /><NumberCell label={`Lane ${index + 1} mileage rate`} value={rule.rate_per_mile} onChange={(value) => updateRule(index, { rate_per_mile: value })} /><NumberCell label={`Lane ${index + 1} stop rate`} value={rule.rate_per_stop} onChange={(value) => updateRule(index, { rate_per_stop: value })} /><NumberCell label={`Lane ${index + 1} included stops`} value={rule.included_stops} onChange={(value) => updateRule(index, { included_stops: value })} step="1" /><NumberCell label={`Lane ${index + 1} minimum charge`} value={rule.minimum_charge} onChange={(value) => updateRule(index, { minimum_charge: value })} /><td className="p-3"><select aria-label={`Lane ${index + 1} mileage rounding`} value={rule.mileage_rounding} onChange={(event) => updateRule(index, { mileage_rounding: event.target.value as LaneRateRule['mileage_rounding'] })} className="input w-36"><option value="exact">Exact</option><option value="nearest_mile">Nearest mile</option><option value="up_to_mile">Round up</option></select></td><RemoveCell label={`Remove lane ${index + 1}`} onClick={() => onChange({ ...detail, lane_rates: detail.lane_rates.filter((_, current) => current !== index) })} /></tr>)}</EditorTable>{!detail.lane_rates.length ? <Empty label="No lane rates yet. Add one to start with governed coverage and baseline commercial terms." /> : null}</EditorSection>
}

function FuelEditor({ detail, onChange }: EditorProps) {
  const updateRule = (index: number, changes: Partial<FuelSurchargeRule>) => onChange({ ...detail, fuel_surcharges: detail.fuel_surcharges.map((row, current) => current === index ? { ...row, ...changes } : row) })
  const add = () => onChange({ ...detail, fuel_surcharges: [...detail.fuel_surcharges, { rule_id: ruleId(detail, 'FUEL'), name: 'Diesel surcharge', rate_pct: 0, basis: 'linehaul_and_minimum', effective_start: detail.version.effective_start, effective_end: detail.version.effective_end }] })
  return <EditorSection title="Fuel surcharges" description="Schedules must fall within the version effective dates. The service date selects the applicable rule." icon={Fuel} onAdd={add} addLabel="Add schedule"><EditorTable headers={['Schedule', 'Rate', 'Calculation basis', 'Effective start', 'Effective end', '']} minWidth="900px">{detail.fuel_surcharges.map((rule, index) => <tr key={rule.rule_id} className="border-t border-border/60"><td className="p-3"><input aria-label={`Fuel schedule ${index + 1} name`} value={rule.name} onChange={(event) => updateRule(index, { name: event.target.value })} className="input w-56" /><RuleId value={rule.rule_id} /></td><NumberCell label={`Fuel schedule ${index + 1} percent`} value={rule.rate_pct} onChange={(value) => updateRule(index, { rate_pct: value })} suffix="%" /><td className="p-3"><select aria-label={`Fuel schedule ${index + 1} basis`} value={rule.basis} onChange={(event) => updateRule(index, { basis: event.target.value as FuelSurchargeRule['basis'] })} className="input w-56"><option value="linehaul">Lane base + mileage</option><option value="linehaul_and_minimum">Linehaul + minimum</option><option value="transportation_subtotal">Transportation subtotal</option></select></td><DateCell label={`Fuel schedule ${index + 1} start`} value={rule.effective_start} onChange={(value) => updateRule(index, { effective_start: value })} /><DateCell label={`Fuel schedule ${index + 1} end`} value={rule.effective_end} onChange={(value) => updateRule(index, { effective_end: value })} /><RemoveCell label={`Remove fuel schedule ${index + 1}`} onClick={() => onChange({ ...detail, fuel_surcharges: detail.fuel_surcharges.filter((_, current) => current !== index) })} /></tr>)}</EditorTable>{!detail.fuel_surcharges.length ? <Empty label="No fuel schedule. Quotes will not add a fuel surcharge." /> : null}</EditorSection>
}

function AccessorialEditor({ detail, templates, onChange }: EditorProps & { templates: RateAccessorialTemplate[] }) {
  const catalog = uniqueByCode([
    ...templates,
    ...detail.accessorials.map((rule) => ({
      code: rule.code,
      name: rule.name,
      charge_type: rule.charge_type,
      rate: rule.rate,
      description: rule.description,
    })),
  ])
  const updateRule = (index: number, changes: Partial<AccessorialRule>) => onChange({ ...detail, accessorials: detail.accessorials.map((row, current) => current === index ? { ...row, ...changes } : row) })
  function applyTemplate(index: number, code: string) {
    const template = catalog.find((row) => row.code === code)
    if (!template) return
    updateRule(index, {
      code: template.code,
      name: template.name,
      charge_type: template.charge_type,
      rate: template.rate,
      description: template.description,
    })
  }
  function add() {
    const used = new Set(detail.accessorials.map((rule) => rule.code))
    const template = catalog.find((row) => !used.has(row.code)) ?? catalog[0]
    if (!template) return
    onChange({ ...detail, accessorials: [...detail.accessorials, { ...template, rule_id: ruleId(detail, 'ACC') }] })
  }
  return <EditorSection title="Accessorials" description="Select a governed charge code; its name, trigger type, description, and starting rate auto-fill from the catalog." icon={ReceiptText} onAdd={add} addLabel="Add accessorial"><EditorTable headers={['Charge code', 'Name and trigger', 'Suggested rate', '']} minWidth="820px">{detail.accessorials.map((rule, index) => <tr key={rule.rule_id} className="border-t border-border/60"><td className="p-3"><select aria-label={`Accessorial ${index + 1} code`} value={rule.code} onChange={(event) => applyTemplate(index, event.target.value)} className="input w-52 font-mono">{catalog.map((template) => <option key={template.code} value={template.code}>{template.code}</option>)}</select><RuleId value={rule.rule_id} /></td><td className="p-3"><div className="font-medium">{rule.name}</div><div className="mt-1 max-w-md text-xs text-muted-foreground">{rule.description}</div><div className="mt-2 text-[10px] uppercase tracking-wide text-muted-foreground">{rule.charge_type.replace('_', ' ')}</div></td><NumberCell label={`Accessorial ${index + 1} rate`} value={rule.rate} onChange={(value) => updateRule(index, { rate: value })} /><RemoveCell label={`Remove accessorial ${index + 1}`} onClick={() => onChange({ ...detail, accessorials: detail.accessorials.filter((_, current) => current !== index) })} /></tr>)}</EditorTable>{!detail.accessorials.length ? <Empty label={catalog.length ? 'No accessorials. Add a governed charge from the catalog.' : 'No accessorial catalog is available yet.'} /> : null}</EditorSection>
}

function TierEditor({ detail, onChange }: EditorProps) {
  const updateRule = (index: number, changes: Partial<VolumeTierRule>, rename = false) => onChange({ ...detail, volume_tiers: detail.volume_tiers.map((row, current) => { if (current !== index) return row; const updated = { ...row, ...changes }; return rename ? { ...updated, name: derivedTierName(updated) } : updated }) })
  const newTier: VolumeTierRule = { rule_id: ruleId(detail, 'TIER'), name: '', period: 'month', unit: 'stops', min_volume: 0, max_volume: null, discount_pct: 0 }
  newTier.name = derivedTierName(newTier)
  const add = () => onChange({ ...detail, volume_tiers: [...detail.volume_tiers, newTier] })
  return <EditorSection title="Volume tiers" description="Period, unit, and range determine the tier label automatically; only the bounds and negotiated discount need entry." icon={Gauge} onAdd={add} addLabel="Add tier"><EditorTable headers={['Tier', 'Period', 'Unit', 'Minimum volume', 'Maximum volume', 'Discount', '']} minWidth="980px">{detail.volume_tiers.map((rule, index) => <tr key={rule.rule_id} className="border-t border-border/60"><td className="p-3"><div className="font-medium">{rule.name}</div><div className="mt-1 text-[10px] text-muted-foreground">Auto-filled from range</div><RuleId value={rule.rule_id} /></td><SelectCell label={`Volume tier ${index + 1} period`} value={rule.period} options={['route', 'week', 'month', 'quarter']} onChange={(value) => updateRule(index, { period: value as VolumeTierRule['period'] }, true)} /><SelectCell label={`Volume tier ${index + 1} unit`} value={rule.unit} options={['stops', 'routes', 'cases', 'miles']} onChange={(value) => updateRule(index, { unit: value as VolumeTierRule['unit'] }, true)} /><NumberCell label={`Volume tier ${index + 1} minimum`} value={rule.min_volume} onChange={(value) => updateRule(index, { min_volume: value }, true)} step="1" /><td className="p-3"><input aria-label={`Volume tier ${index + 1} maximum`} type="number" min="0" step="1" value={rule.max_volume ?? ''} onChange={(event) => updateRule(index, { max_volume: event.target.value === '' ? null : Number(event.target.value) }, true)} placeholder="No maximum" className="input w-32" /></td><NumberCell label={`Volume tier ${index + 1} discount`} value={rule.discount_pct} onChange={(value) => updateRule(index, { discount_pct: value })} suffix="%" /><RemoveCell label={`Remove volume tier ${index + 1}`} onClick={() => onChange({ ...detail, volume_tiers: detail.volume_tiers.filter((_, current) => current !== index) })} /></tr>)}</EditorTable>{!detail.volume_tiers.length ? <Empty label="No tiers. Base rates will apply at every volume." /> : null}</EditorSection>
}

function CommitmentEditor({ detail, onChange }: EditorProps) {
  const updateRule = (index: number, changes: Partial<CapacityCommitmentRule>, rename = false) => onChange({ ...detail, capacity_commitments: detail.capacity_commitments.map((row, current) => { if (current !== index) return row; const updated = { ...row, ...changes }; return rename ? { ...updated, name: derivedCommitmentName(updated) } : updated }) })
  const newCommitment: CapacityCommitmentRule = { rule_id: ruleId(detail, 'COMMIT'), name: '', period: 'month', unit: 'stops', committed_quantity: 50, capacity_quantity: 75, current_utilization: 0, shortfall_rate: 10, overage_rate: 15 }
  newCommitment.name = derivedCommitmentName(newCommitment)
  const add = () => onChange({ ...detail, capacity_commitments: [...detail.capacity_commitments, newCommitment] })
  return <EditorSection title="Capacity commitments" description="Period and unit determine the label. Utilization is operational data and remains read-only while contract terms are edited." icon={ShieldCheck} onAdd={add} addLabel="Add commitment"><EditorTable headers={['Commitment', 'Period', 'Unit', 'Committed', 'Maximum', 'Utilized', 'Shortfall rate', 'Overage rate', '']} minWidth="1160px">{detail.capacity_commitments.map((rule, index) => <tr key={rule.rule_id} className="border-t border-border/60"><td className="p-3"><div className="font-medium">{rule.name}</div><div className="mt-1 text-[10px] text-muted-foreground">Auto-filled from period and unit</div><RuleId value={rule.rule_id} /></td><SelectCell label={`Commitment ${index + 1} period`} value={rule.period} options={['route', 'week', 'month', 'quarter']} onChange={(value) => updateRule(index, { period: value as CapacityCommitmentRule['period'] }, true)} /><SelectCell label={`Commitment ${index + 1} unit`} value={rule.unit} options={['stops', 'routes', 'cases', 'miles']} onChange={(value) => updateRule(index, { unit: value as CapacityCommitmentRule['unit'] }, true)} /><NumberCell label={`Commitment ${index + 1} committed quantity`} value={rule.committed_quantity} onChange={(value) => updateRule(index, { committed_quantity: value })} step="1" /><NumberCell label={`Commitment ${index + 1} capacity quantity`} value={rule.capacity_quantity} onChange={(value) => updateRule(index, { capacity_quantity: value })} step="1" /><td className="p-3"><div className="w-28 rounded-md border border-border bg-background/35 px-3 py-2 text-sm tabular-nums text-muted-foreground" aria-label={`Commitment ${index + 1} current utilization`}>{formatNumber(rule.current_utilization)}</div><div className="mt-1 text-[10px] text-muted-foreground">Tracked</div></td><NumberCell label={`Commitment ${index + 1} shortfall rate`} value={rule.shortfall_rate} onChange={(value) => updateRule(index, { shortfall_rate: value })} /><NumberCell label={`Commitment ${index + 1} overage rate`} value={rule.overage_rate} onChange={(value) => updateRule(index, { overage_rate: value })} /><RemoveCell label={`Remove commitment ${index + 1}`} onClick={() => onChange({ ...detail, capacity_commitments: detail.capacity_commitments.filter((_, current) => current !== index) })} /></tr>)}</EditorTable>{!detail.capacity_commitments.length ? <Empty label="No commitment. Add one to start with a monthly stop-capacity template." /> : null}</EditorSection>
}

function LaneRates({ detail }: { detail: Detail }) { return <DataSection title="Lane rates" description="Rules are evaluated by priority and lane specificity; exact matches win over regional fallbacks." icon={MapPinned}>{detail.lane_rates.length ? <EditorTable headers={['Lane', 'Priority', 'Lane base', 'Per mile', 'Per stop', 'Included', 'Minimum', 'Mileage']} minWidth="980px">{detail.lane_rates.map((rule) => <tr key={rule.rule_id} className="border-t border-border/60"><td className="px-4 py-3"><div className="font-medium">{rule.lane_name}</div><div className="mt-1 text-xs text-muted-foreground">{rule.origin} → {rule.destination}</div><RuleId value={rule.rule_id} /></td><ReadCell value={String(rule.priority)} /><ReadCell value={formatCurrency(rule.flat_rate)} /><ReadCell value={formatCurrency(rule.rate_per_mile)} /><ReadCell value={formatCurrency(rule.rate_per_stop)} /><ReadCell value={String(rule.included_stops)} /><ReadCell value={formatCurrency(rule.minimum_charge)} /><ReadCell value={rule.mileage_rounding.replaceAll('_', ' ')} /></tr>)}</EditorTable> : <Empty label="No lane rates are defined for this version." />}</DataSection> }
function FuelSurcharges({ detail }: { detail: Detail }) { return <DataSection title="Fuel surcharges" description="Only schedules effective on the route service date are considered." icon={Fuel}>{detail.fuel_surcharges.length ? <div className="grid gap-3 p-4 lg:grid-cols-2">{detail.fuel_surcharges.map((rule) => <div key={rule.rule_id} className="rounded-md border border-border/60 p-3"><div className="flex justify-between gap-3"><div><div className="font-medium">{rule.name}</div><RuleId value={rule.rule_id} /></div><div className="text-lg font-semibold">{formatPercent(rule.rate_pct)}</div></div><div className="mt-3 grid grid-cols-2 gap-3"><MetaBox label="Basis" value={rule.basis.replaceAll('_', ' ')} /><MetaBox label="Effective" value={formatRange(rule.effective_start, rule.effective_end)} /></div></div>)}</div> : <Empty label="No fuel surcharge is defined." />}</DataSection> }
function Accessorials({ detail }: { detail: Detail }) { return <DataSection title="Accessorials" description="Typed triggers prevent free-form fees from entering a scenario silently." icon={ReceiptText}>{detail.accessorials.length ? <div className="divide-y divide-border/60">{detail.accessorials.map((rule) => <div key={rule.rule_id} className="p-4"><div className="flex justify-between gap-3"><div><div className="font-medium">{rule.name}</div><div className="mt-1 text-xs text-muted-foreground">{rule.description}</div></div><div className="text-right"><div className="font-semibold">{formatCurrency(rule.rate)}</div><div className="text-[10px] uppercase text-muted-foreground">{rule.charge_type.replace('_', ' ')}</div></div></div><RuleId value={`${rule.code} · ${rule.rule_id}`} /></div>)}</div> : <Empty label="No accessorials are defined." />}</DataSection> }
function VolumeTiers({ detail }: { detail: Detail }) { return <DataSection title="Volume tiers" description="Projected period volume selects one discount band before minimum-charge evaluation." icon={Gauge}>{detail.volume_tiers.length ? <EditorTable headers={['Tier', 'Range', 'Period', 'Discount']} minWidth="680px">{detail.volume_tiers.map((rule) => <tr key={rule.rule_id} className="border-t border-border/60"><td className="p-4"><div className="font-medium">{rule.name}</div><RuleId value={rule.rule_id} /></td><ReadCell value={`${formatNumber(rule.min_volume)}–${rule.max_volume === null ? '∞' : formatNumber(rule.max_volume)} ${rule.unit}`} /><ReadCell value={rule.period} /><ReadCell value={formatPercent(rule.discount_pct)} /></tr>)}</EditorTable> : <Empty label="No volume tiers are defined." />}</DataSection> }
function Commitments({ detail }: { detail: Detail }) { return <DataSection title="Capacity commitments" description="Commitment and maximum capacity are evaluated against projected period volume." icon={ShieldCheck}>{detail.capacity_commitments.length ? <div className="grid gap-3 p-4 lg:grid-cols-2">{detail.capacity_commitments.map((rule) => <div key={rule.rule_id} className="rounded-md border border-border/60 p-3"><div className="font-medium">{rule.name}</div><RuleId value={rule.rule_id} /><div className="mt-4 grid grid-cols-3 gap-3"><MetaBox label="Utilized" value={`${formatNumber(rule.current_utilization)} ${rule.unit}`} /><MetaBox label="Committed" value={`${formatNumber(rule.committed_quantity)} ${rule.unit}`} /><MetaBox label="Maximum" value={`${formatNumber(rule.capacity_quantity)} ${rule.unit}`} /></div><Progress value={rule.current_utilization} max={rule.capacity_quantity} /></div>)}</div> : <Empty label="No capacity commitments are defined." />}</DataSection> }

function VersionHistory({ detail }: { detail: Detail }) {
  const versions = detail.version_history.length ? detail.version_history : [detail.version]
  return <DataSection title="Version history" description="Published versions are immutable and historical quotes remain pinned to their original snapshot." icon={FileClock}><div className="divide-y divide-border/60">{versions.map((version) => { const selected = version.version_id === detail.version.version_id; return <div key={version.version_id} className={cn('flex items-start gap-4 p-4', selected && 'bg-primary/5')}><div className={cn('mt-0.5 rounded-full p-2', selected ? 'bg-primary/15 text-primary' : 'bg-secondary text-muted-foreground')}><FileClock className="h-4 w-4" /></div><div className="min-w-0 flex-1"><div className="flex flex-wrap justify-between gap-3"><div className="font-medium">Version {version.version_number} · <span className="capitalize">{version.status}</span>{selected ? ' · Selected' : ''}</div><div className="text-xs text-muted-foreground">{version.published_at ? new Date(version.published_at).toLocaleDateString() : 'Not published'}</div></div><p className="mt-1 text-xs text-muted-foreground">{version.published_by ? `Published by ${version.published_by}` : 'Working draft'} · {formatRange(version.effective_start, version.effective_end)}</p>{version.change_reason ? <p className="mt-2 text-xs">{version.change_reason}</p> : null}<div className="mt-3 flex flex-wrap items-center justify-between gap-3"><span className="font-mono text-[11px] text-muted-foreground">{version.version_id}</span>{!selected ? <Link to={`/rates/contracts/${encodeURIComponent(detail.contract_id)}/versions/${encodeURIComponent(version.version_id)}/${version.status === 'draft' ? 'lane-rates' : 'version-history'}`} className="text-xs font-medium text-primary hover:underline">Open version</Link> : null}</div></div></div>})}</div></DataSection>
}

function CreateVersionDialog({ detail, pending, error, onClose, onSubmit }: { detail: Detail; pending: boolean; error: Error | null; onClose: () => void; onSubmit: (request: RateVersionCreateRequest) => void }) {
  const suggestedStart = nextDay(detail.version.effective_end) ?? new Date().toISOString().slice(0, 10)
  const suggestedEnd = addYear(suggestedStart)
  const [form, setForm] = useState<RateVersionCreateRequest>({ source_version_id: detail.version.version_id, effective_start: suggestedStart, effective_end: suggestedEnd, change_reason: '' })
  function submit(event: FormEvent) { event.preventDefault(); onSubmit(form) }
  return <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/60 p-4" onMouseDown={(event) => { if (event.currentTarget === event.target) onClose() }}><form onSubmit={submit} role="dialog" aria-modal="true" aria-labelledby="create-version-title" className="w-full max-w-lg rounded-lg border border-border bg-card shadow-2xl"><div className="flex justify-between border-b border-border p-4"><div><h2 id="create-version-title" className="font-semibold">Create Draft Version {detail.version.version_number + 1}</h2><p className="mt-1 text-xs text-muted-foreground">Clone all five rule tabs from Version {detail.version.version_number}.</p></div><button type="button" onClick={onClose} aria-label="Close"><X className="h-4 w-4" /></button></div><div className="grid gap-4 p-5"><div className="grid grid-cols-2 gap-3"><EditorField label="Effective start"><input required type="date" aria-label="New version effective start" value={form.effective_start} onChange={(event) => setForm({ ...form, effective_start: event.target.value })} className="input w-full" /></EditorField><EditorField label="Effective end"><input required type="date" min={form.effective_start} aria-label="New version effective end" value={form.effective_end} onChange={(event) => setForm({ ...form, effective_end: event.target.value })} className="input w-full" /></EditorField></div><EditorField label="Change summary"><textarea required autoFocus rows={3} aria-label="New version change summary" value={form.change_reason} onChange={(event) => setForm({ ...form, change_reason: event.target.value })} placeholder="Describe the negotiation, renewal, or pricing change." className="input resize-none" /></EditorField>{error ? <div className="rounded border border-destructive/40 bg-destructive/10 p-3 text-xs text-destructive">{friendlyError(error)}</div> : null}</div><div className="flex justify-end gap-2 border-t border-border p-4"><button type="button" onClick={onClose} disabled={pending} className="rounded-md border border-border px-3 py-2 text-sm">Cancel</button><button type="submit" disabled={pending || !form.change_reason.trim()} className="inline-flex items-center gap-2 rounded-md bg-primary px-3 py-2 text-sm font-semibold text-primary-foreground disabled:opacity-50">{pending ? <Loader2 className="h-4 w-4 animate-spin" /> : <CopyPlus className="h-4 w-4" />}Create draft</button></div></form></div>
}

interface EditorProps { detail: Detail; onChange: (detail: Detail) => void }
function EditorSection({ title, description, icon: Icon, onAdd, addLabel, children }: { title: string; description: string; icon: typeof MapPinned; onAdd: () => void; addLabel: string; children: ReactNode }) { return <section className="overflow-hidden rounded-lg border border-border bg-card"><div className="flex flex-wrap items-start justify-between gap-3 border-b border-border px-4 py-3"><div className="flex items-start gap-2"><Icon className="mt-0.5 h-4 w-4 text-primary" /><div><h2 className="text-sm font-semibold">{title}</h2><p className="mt-1 text-xs text-muted-foreground">{description}</p></div></div><button type="button" onClick={onAdd} className="inline-flex items-center gap-1.5 rounded-md border border-primary/40 px-3 py-2 text-xs font-medium text-primary"><Plus className="h-3.5 w-3.5" />{addLabel}</button></div>{children}</section> }
function EditorTable({ headers, minWidth, children }: { headers: string[]; minWidth: string; children: ReactNode }) { return <div className="overflow-x-auto"><table className="w-full text-left text-sm" style={{ minWidth }}><thead className="bg-background/40 text-xs uppercase tracking-wide text-muted-foreground"><tr>{headers.map((header, index) => <th key={`${header}-${index}`} className="px-3 py-3">{header}</th>)}</tr></thead><tbody>{children}</tbody></table></div> }
function NumberCell({ label, value, onChange, step = '0.01', suffix }: { label: string; value: number; onChange: (value: number) => void; step?: string; suffix?: string }) { return <td className="p-3"><div className="relative"><input aria-label={label} type="number" min="0" step={step} value={value} onChange={(event) => onChange(Number(event.target.value))} className={cn('input w-28 tabular-nums', suffix && 'pr-7')} />{suffix ? <span className="pointer-events-none absolute right-3 top-2.5 text-xs text-muted-foreground">{suffix}</span> : null}</div></td> }
function DateCell({ label, value, onChange }: { label: string; value: string | null; onChange: (value: string) => void }) { return <td className="p-3"><input aria-label={label} type="date" value={value ?? ''} onChange={(event) => onChange(event.target.value)} className="input w-40" /></td> }
function SelectCell({ label, value, options, onChange }: { label: string; value: string; options: string[]; onChange: (value: string) => void }) { return <td className="p-3"><select aria-label={label} value={value} onChange={(event) => onChange(event.target.value)} className="input w-28 capitalize">{options.map((option) => <option key={option} value={option}>{option}</option>)}</select></td> }
function RemoveCell({ label, onClick }: { label: string; onClick: () => void }) { return <td className="p-3 text-right"><button type="button" onClick={onClick} aria-label={label} className="rounded p-2 text-muted-foreground hover:bg-destructive/10 hover:text-destructive"><Trash2 className="h-4 w-4" /></button></td> }
function ReadCell({ value }: { value: string }) { return <td className="px-4 py-3 capitalize tabular-nums">{value}</td> }
function RuleId({ value }: { value: string }) { return <div className="mt-1.5 font-mono text-[10px] text-muted-foreground">{value}</div> }
function SaveBeforeTesting({ onSave, pending }: { onSave: () => void; pending: boolean }) { return <div className="rounded-lg border border-amber-400/30 bg-card px-6 py-16 text-center"><Save className="mx-auto h-7 w-7 text-amber-400" /><h2 className="mt-3 text-sm font-semibold">Save before testing this draft</h2><p className="mt-1 text-xs text-muted-foreground">The quote tester uses the last transactional draft snapshot.</p><button type="button" onClick={onSave} disabled={pending} className="mt-4 inline-flex items-center gap-2 rounded-md bg-primary px-3 py-2 text-sm font-semibold text-primary-foreground">{pending ? <Loader2 className="h-4 w-4 animate-spin" /> : <Save className="h-4 w-4" />}Save draft</button></div> }
function DataSection({ title, description, icon: Icon, children }: { title: string; description: string; icon: typeof MapPinned; children: ReactNode }) { return <section className="overflow-hidden rounded-lg border border-border bg-card"><div className="flex items-start gap-2 border-b border-border px-4 py-3"><Icon className="mt-0.5 h-4 w-4 text-primary" /><div><h2 className="text-sm font-semibold">{title}</h2><p className="mt-1 text-xs text-muted-foreground">{description}</p></div></div>{children}</section> }
function EditorField({ label, children }: { label: string; children: ReactNode }) { return <label className="grid gap-1 text-xs font-medium"><span>{label}</span>{children}</label> }
function OverviewValue({ icon: Icon, label, value }: { icon: typeof MapPinned; label: string; value: string }) { return <div className="flex items-start gap-2"><Icon className="mt-0.5 h-4 w-4 text-primary" /><div><div className="text-xs text-muted-foreground">{label}</div><div className="mt-1 text-sm font-medium">{value}</div></div></div> }
function MetaBox({ label, value }: { label: string; value: string }) { return <div><div className="text-[10px] uppercase tracking-wide text-muted-foreground">{label}</div><div className="mt-1 text-xs font-medium capitalize tabular-nums">{value}</div></div> }
function Progress({ value, max }: { value: number; max: number }) { return <div className="mt-4 h-2 overflow-hidden rounded-full bg-secondary"><div className="h-full bg-primary" style={{ width: `${Math.min(100, max ? value / max * 100 : 0)}%` }} /></div> }
function Empty({ label }: { label: string }) { return <div className="px-5 py-12 text-center text-sm text-muted-foreground">{label}</div> }
function StatusPill({ status }: { status: Detail['version']['status'] }) { return <span className={cn('rounded-full border px-2 py-1 text-[11px] font-medium capitalize', status === 'published' && 'border-primary/35 bg-primary/10 text-primary', status === 'draft' && 'border-amber-400/35 bg-amber-400/10 text-amber-400', status === 'expired' && 'border-border text-muted-foreground')}>{status}</span> }
function DetailSkeleton() { return <div className="space-y-4 px-4 py-5 sm:px-6 lg:px-8"><div className="h-20 animate-pulse rounded-lg bg-card" /><div className="h-36 animate-pulse rounded-lg bg-card" /><div className="h-96 animate-pulse rounded-lg bg-card" /></div> }
function ruleId(detail: Detail, family: string) { return `${detail.version.version_id}_${family}_${globalThis.crypto?.randomUUID?.().slice(0, 8) ?? Math.random().toString(16).slice(2, 10)}` }
function formatDate(value: string) { return new Date(`${value}T12:00:00`).toLocaleDateString(undefined, { month: 'short', day: 'numeric', year: 'numeric' }) }
function formatRange(start: string | null, end: string | null) { return `${start ? formatDate(start) : 'Open'} – ${end ? formatDate(end) : 'Open'}` }
function nextDay(value: string | null) { if (!value) return null; const result = new Date(`${value}T12:00:00`); result.setDate(result.getDate() + 1); return result.toISOString().slice(0, 10) }
function addYear(value: string) { const result = new Date(`${value}T12:00:00`); result.setFullYear(result.getFullYear() + 1); result.setDate(result.getDate() - 1); return result.toISOString().slice(0, 10) }
function unique(values: string[]) { return Array.from(new Set(values)) }
function uniqueByCode(values: RateAccessorialTemplate[]) { return Array.from(new Map(values.map((value) => [value.code, value])).values()) }
function derivedLaneName(origin: string, destination: string, depots: Depot[]) {
  const originLabel = origin === '*' ? 'Any origin' : depots.find((depot) => depot.depot_id === origin)?.name ?? origin
  const destinationLabel = destination === '*' ? 'Any destination' : destination
  return `${originLabel} → ${destinationLabel}`
}
function periodAdjective(period: VolumeTierRule['period']) { return period === 'route' ? 'per-route' : period === 'week' ? 'weekly' : period === 'quarter' ? 'quarterly' : 'monthly' }
function unitSingular(unit: CapacityCommitmentRule['unit']) { return unit === 'cases' ? 'case' : unit.endsWith('s') ? unit.slice(0, -1) : unit }
function derivedTierName(rule: VolumeTierRule) { return `${formatNumber(rule.min_volume)}${rule.max_volume === null ? '+' : `–${formatNumber(rule.max_volume)}`} ${periodAdjective(rule.period)} ${rule.unit}` }
function derivedCommitmentName(rule: CapacityCommitmentRule) { return `${periodAdjective(rule.period).replace('per-route', 'Route')} ${unitSingular(rule.unit)} capacity commitment`.replace(/^\w/, (value) => value.toUpperCase()) }
function friendlyError(error: unknown) { return error instanceof Error ? error.message.replace(/^\d+ [^:]+:\s*/, '') : String(error) }
