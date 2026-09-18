import { useEffect, useMemo, useState } from 'react'
import type { FormEvent } from 'react'
import { Link } from 'react-router-dom'
import { useNavigate } from 'react-router-dom'
import { AlertTriangle, ArrowRight, CalendarDays, FileCheck2, Loader2, Pencil, Plus, Search, ShieldCheck, X } from 'lucide-react'
import ErrorState from '@/components/ErrorState'
import { useCarriers, useCreateRateContract, useRateContracts } from '@/api/queries'
import type { RateContractCreateRequest, RateContractStatus } from '@/api/types'
import { formatNumber } from '@/lib/format'
import { cn } from '@/lib/utils'

export default function RatesPage() {
  const navigate = useNavigate()
  const serviceDate = new Date().toISOString().slice(0, 10)
  const [search, setSearch] = useState('')
  const [status, setStatus] = useState<'all' | RateContractStatus>('all')
  const contracts = useRateContracts(serviceDate)
  const carriers = useCarriers()
  const createContract = useCreateRateContract()
  const [showCreate, setShowCreate] = useState(false)
  const filtered = useMemo(() => {
    const term = search.trim().toLowerCase()
    return (contracts.data ?? []).filter((contract) => {
      const matchesStatus = status === 'all' || contract.status === status
      const matchesSearch =
        !term ||
        contract.contract_name.toLowerCase().includes(term) ||
        contract.carrier_name.toLowerCase().includes(term) ||
        contract.contract_id.toLowerCase().includes(term)
      return matchesStatus && matchesSearch
    })
  }, [contracts.data, search, status])

  if (contracts.error) {
    return <ErrorState title="Could not load Rates & Contracts" error={contracts.error} />
  }

  const published = contracts.data?.filter((row) => row.status === 'published') ?? []
  const covered = published.filter((row) => row.coverage_status === 'covered')
  const unavailable = contracts.data?.filter((row) => row.coverage_status !== 'covered') ?? []
  const totalCommitted = published.reduce((sum, row) => sum + row.committed_quantity, 0)
  const totalUtilized = published.reduce((sum, row) => sum + row.current_utilization, 0)
  const freshness = contracts.data?.[0]?.freshness_at

  return (
    <div className="flex flex-col gap-5 px-4 py-5 sm:px-6 lg:px-8">
      {contracts.isLoading ? (
        <RatesSkeleton />
      ) : (
        <>
          <section className="grid gap-3 sm:grid-cols-2 xl:grid-cols-4">
            <SummaryCard icon={FileCheck2} label="Published contracts" value={formatNumber(published.length)} detail={`Effective ${formatDate(serviceDate)}`} />
            <SummaryCard icon={ShieldCheck} label="Covered contracts" value={formatNumber(covered.length)} detail={`${unavailable.length} need attention`} />
            <SummaryCard icon={CalendarDays} label="Committed capacity" value={`${formatNumber(totalUtilized)} / ${formatNumber(totalCommitted)}`} detail="Stops · current month" />
            <SummaryCard icon={AlertTriangle} label="Unavailable" value={formatNumber(unavailable.length)} detail="Expired, future, or uncovered" tone={unavailable.length ? 'warning' : 'default'} />
          </section>

          <section className="overflow-hidden rounded-lg border border-border bg-card">
            <div className="flex flex-wrap items-center justify-between gap-3 border-b border-border px-4 py-3">
              <div>
                <h2 className="text-sm font-semibold">Contract rate book</h2>
                <p className="mt-1 text-xs text-muted-foreground">
                  Source: Lakebase rate book{freshness ? ` · refreshed ${new Date(freshness).toLocaleString()}` : ''}
                </p>
              </div>
              <div className="flex flex-wrap gap-2">
                <button type="button" onClick={() => setShowCreate(true)} className="inline-flex items-center gap-1.5 rounded-md bg-primary px-3 py-2 text-sm font-semibold text-primary-foreground"><Plus className="h-4 w-4" />New contract</button>
                <label className="relative">
                  <Search className="pointer-events-none absolute left-2.5 top-2.5 h-4 w-4 text-muted-foreground" />
                  <input
                    aria-label="Search contracts"
                    value={search}
                    onChange={(event) => setSearch(event.target.value)}
                    placeholder="Search contracts"
                    className="w-56 rounded-md border border-border bg-background py-2 pl-8 pr-3 text-sm"
                  />
                </label>
                <select
                  aria-label="Filter contract status"
                  value={status}
                  onChange={(event) => setStatus(event.target.value as typeof status)}
                  className="rounded-md border border-border bg-background px-3 py-2 text-sm"
                >
                  <option value="all">All statuses</option>
                  <option value="published">Published</option>
                  <option value="draft">Future / draft</option>
                  <option value="expired">Expired</option>
                </select>
              </div>
            </div>

            {filtered.length === 0 ? (
              <div className="px-6 py-14 text-center">
                <div className="text-sm font-medium">No contracts match these filters.</div>
                <button type="button" onClick={() => { setSearch(''); setStatus('all') }} className="mt-2 text-xs text-primary hover:underline">
                  Clear filters
                </button>
              </div>
            ) : (
              <div className="overflow-x-auto">
                <table className="w-full min-w-[900px] text-left text-sm">
                  <thead className="bg-background/40 text-xs uppercase tracking-wide text-muted-foreground">
                    <tr>
                      <th className="px-4 py-3">Carrier / contract</th>
                      <th className="px-4 py-3">Version</th>
                      <th className="px-4 py-3">Effective</th>
                      <th className="px-4 py-3">Rules</th>
                      <th className="px-4 py-3">Commitment</th>
                      <th className="px-4 py-3">Status</th>
                      <th className="px-4 py-3"><span className="sr-only">Open</span></th>
                    </tr>
                  </thead>
                  <tbody>
                    {filtered.map((contract) => (
                      <tr key={contract.contract_id} className="border-t border-border/60 hover:bg-accent/25">
                        <td className="px-4 py-3">
                          <div className="font-medium">{contract.contract_name}</div>
                          <div className="mt-0.5 text-xs text-muted-foreground">{contract.carrier_name} · {contract.contract_id}</div>
                        </td>
                        <td className="px-4 py-3 tabular-nums"><div>v{contract.version.version_number}</div>{contract.draft_version && contract.draft_version.version_id !== contract.version.version_id ? <div className="mt-1 text-xs font-medium text-amber-400">Draft v{contract.draft_version.version_number}</div> : null}</td>
                        <td className="px-4 py-3 text-xs tabular-nums">{formatRange(contract.version.effective_start, contract.version.effective_end)}</td>
                        <td className="px-4 py-3 text-xs">{contract.lane_count} lanes · {contract.accessorial_count} accessorials · {contract.volume_tier_count} tiers</td>
                        <td className="px-4 py-3">
                          <div className="font-medium tabular-nums">{formatNumber(contract.current_utilization)} / {formatNumber(contract.committed_quantity)} stops</div>
                          <div className="mt-1 h-1.5 w-28 overflow-hidden rounded-full bg-secondary">
                            <div className="h-full bg-primary" style={{ width: `${Math.min(100, contract.committed_quantity ? contract.current_utilization / contract.committed_quantity * 100 : 0)}%` }} />
                          </div>
                        </td>
                        <td className="px-4 py-3"><StatusBadge status={contract.status} /></td>
                        <td className="px-4 py-3 text-right">
                          <div className="inline-flex items-center gap-2">
                            <Link
                              aria-label={contract.draft_version ? `Edit draft for ${contract.contract_name}` : `Create a new version of ${contract.contract_name}`}
                              title={contract.draft_version ? 'Edit draft' : 'Create new version'}
                              to={contract.draft_version
                                ? `/rates/contracts/${encodeURIComponent(contract.contract_id)}/versions/${encodeURIComponent(contract.draft_version.version_id)}/lane-rates`
                                : `/rates/contracts/${encodeURIComponent(contract.contract_id)}/versions/${encodeURIComponent(contract.version.version_id)}/overview?createVersion=1`}
                              className="rounded-md border border-border p-1.5 text-muted-foreground transition-colors hover:border-primary/40 hover:bg-primary/5 hover:text-primary"
                            >
                              <Pencil className="h-3.5 w-3.5" />
                            </Link>
                            <Link
                              aria-label={`Open ${contract.contract_name}`}
                              to={`/rates/contracts/${encodeURIComponent(contract.contract_id)}/versions/${encodeURIComponent(contract.draft_version?.version_id ?? contract.version.version_id)}/${contract.draft_version ? 'lane-rates' : 'overview'}`}
                              className="inline-flex items-center gap-1 text-xs font-medium text-primary hover:underline"
                            >
                              Open <ArrowRight className="h-3.5 w-3.5" />
                            </Link>
                          </div>
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            )}
          </section>
          {showCreate ? <CreateContractDialog carriers={carriers.data ?? []} pending={createContract.isPending} error={createContract.error} onClose={() => { if (!createContract.isPending) setShowCreate(false) }} onSubmit={(payload) => createContract.mutate(payload, { onSuccess: (detail) => { setShowCreate(false); navigate(`/rates/contracts/${encodeURIComponent(detail.contract_id)}/versions/${encodeURIComponent(detail.version.version_id)}/lane-rates`) } })} /> : null}
        </>
      )}
    </div>
  )
}

function CreateContractDialog({ carriers, pending, error, onClose, onSubmit }: { carriers: { carrier_id: string; carrier_name: string }[]; pending: boolean; error: Error | null; onClose: () => void; onSubmit: (payload: RateContractCreateRequest) => void }) {
  const today = new Date().toISOString().slice(0, 10)
  const end = new Date(`${today}T12:00:00`)
  end.setFullYear(end.getFullYear() + 1)
  end.setDate(end.getDate() - 1)
  const [form, setForm] = useState<RateContractCreateRequest>({ carrier_id: carriers[0]?.carrier_id ?? '', contract_name: '', currency: 'USD', effective_start: today, effective_end: end.toISOString().slice(0, 10) })
  useEffect(() => {
    if (!form.carrier_id && carriers[0]) {
      setForm((current) => ({ ...current, carrier_id: carriers[0].carrier_id }))
    }
  }, [carriers, form.carrier_id])

  function submit(event: FormEvent) {
    event.preventDefault()
    onSubmit(form)
  }

  return <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/60 p-4" role="presentation" onMouseDown={(event) => { if (event.currentTarget === event.target) onClose() }}><form onSubmit={submit} role="dialog" aria-modal="true" aria-labelledby="new-contract-title" className="w-full max-w-lg rounded-lg border border-border bg-card shadow-2xl"><div className="flex items-start justify-between border-b border-border px-5 py-4"><div><h2 id="new-contract-title" className="text-base font-semibold">New contract rate book</h2><p className="mt-1 text-xs text-muted-foreground">Creates the contract and an editable Draft Version 1.</p></div><button type="button" onClick={onClose} disabled={pending} aria-label="Close" className="rounded p-1 text-muted-foreground hover:bg-accent hover:text-foreground"><X className="h-4 w-4" /></button></div><div className="grid gap-4 p-5"><label className="grid gap-1 text-xs font-medium">Carrier<select required aria-label="New contract carrier" value={form.carrier_id} onChange={(event) => setForm({ ...form, carrier_id: event.target.value })} className="input"><option value="" disabled>Select carrier</option>{carriers.map((carrier) => <option key={carrier.carrier_id} value={carrier.carrier_id}>{carrier.carrier_name}</option>)}</select></label><label className="grid gap-1 text-xs font-medium">Contract name<input required autoFocus aria-label="New contract name" value={form.contract_name} onChange={(event) => setForm({ ...form, contract_name: event.target.value })} placeholder="e.g. Great Lakes Dedicated 2027" className="input" /></label><div className="grid grid-cols-2 gap-3"><label className="grid gap-1 text-xs font-medium">Effective start<input required type="date" aria-label="New contract effective start" value={form.effective_start} onChange={(event) => setForm({ ...form, effective_start: event.target.value })} className="input" /></label><label className="grid gap-1 text-xs font-medium">Effective end<input required type="date" min={form.effective_start} aria-label="New contract effective end" value={form.effective_end} onChange={(event) => setForm({ ...form, effective_end: event.target.value })} className="input" /></label></div><label className="grid gap-1 text-xs font-medium">Currency<select aria-label="New contract currency" value={form.currency} onChange={(event) => setForm({ ...form, currency: event.target.value })} className="input"><option value="USD">USD</option><option value="CAD">CAD</option><option value="MXN">MXN</option></select></label>{error ? <div className="rounded-md border border-destructive/40 bg-destructive/10 p-3 text-xs text-destructive">{String(error)}</div> : null}</div><div className="flex justify-end gap-2 border-t border-border px-5 py-4"><button type="button" onClick={onClose} disabled={pending} className="rounded-md border border-border px-3 py-2 text-sm">Cancel</button><button type="submit" disabled={pending || !form.carrier_id || !form.contract_name.trim()} className="inline-flex items-center gap-2 rounded-md bg-primary px-3 py-2 text-sm font-semibold text-primary-foreground disabled:opacity-50">{pending ? <Loader2 className="h-4 w-4 animate-spin" /> : <Plus className="h-4 w-4" />}Create draft</button></div></form></div>
}

function SummaryCard({ icon: Icon, label, value, detail, tone = 'default' }: { icon: typeof FileCheck2; label: string; value: string; detail: string; tone?: 'default' | 'warning' }) {
  return (
    <div className={cn('rounded-lg border bg-card p-4', tone === 'warning' ? 'border-destructive/35' : 'border-border')}>
      <div className="flex items-center gap-2 text-xs text-muted-foreground"><Icon className={cn('h-4 w-4', tone === 'warning' ? 'text-destructive' : 'text-primary')} />{label}</div>
      <div className="mt-2 text-2xl font-semibold tabular-nums">{value}</div>
      <div className="mt-1 text-xs text-muted-foreground">{detail}</div>
    </div>
  )
}

function StatusBadge({ status }: { status: RateContractStatus }) {
  return <span className={cn('rounded-full border px-2 py-1 text-[11px] font-medium capitalize', status === 'published' && 'border-primary/35 bg-primary/10 text-primary', status === 'draft' && 'border-border text-muted-foreground', status === 'expired' && 'border-destructive/35 bg-destructive/10 text-destructive')}>{status}</span>
}

function RatesSkeleton() {
  return <div className="space-y-4"><div className="grid gap-3 sm:grid-cols-2 xl:grid-cols-4">{Array.from({ length: 4 }).map((_, index) => <div key={index} className="h-28 animate-pulse rounded-lg border border-border bg-card" />)}</div><div className="h-80 animate-pulse rounded-lg border border-border bg-card" /></div>
}

function formatDate(value: string) {
  return new Date(`${value}T12:00:00`).toLocaleDateString(undefined, { month: 'short', day: 'numeric', year: 'numeric' })
}

function formatRange(start: string | null, end: string | null) {
  return `${start ? formatDate(start) : 'Open'} – ${end ? formatDate(end) : 'Open'}`
}
