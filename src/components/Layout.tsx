import { useEffect, useMemo, useRef, useState } from 'react'
import { createPortal } from 'react-dom'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { Link, NavLink, useLocation, useNavigate } from 'react-router-dom'
import {
  ArrowLeft,
  Loader2,
  MapPinned,
  Network,
  PlayCircle,
  Route,
  ScrollText,
  Settings,
  Table2,
  Warehouse,
} from 'lucide-react'
import type { ReactNode } from 'react'
import { api } from '@/api/client'
import {
  useCreateNetworkScenario,
  useDepots,
  useNetworkOptions,
  useNetworkOverview,
  useNetworkScenarios,
} from '@/api/queries'
import type { NetworkOverviewParams } from '@/api/types'
import { buildRouteWorkspaceHref, readParentRouteContext } from '@/lib/networkLinks'
import { cn } from '@/lib/utils'
import { useRouteContext } from '@/state/useRouteContext'
import { useScenarioDraft } from '@/state/useScenarioDraft'

const scenarioTabs = [
  { id: 'scenario', label: 'Scenario' },
  { id: 'flow', label: 'Plan flow' },
  { id: 'lanes', label: 'Lane changes' },
  { id: 'charges', label: 'Rate audit' },
  { id: 'exceptions', label: 'Exceptions' },
]

const lowerLevelItems = [
  {
    path: '/analyze',
    label: 'Depot',
    icon: MapPinned,
    activePrefixes: ['/analyze', '/dc'],
  },
  {
    path: '/scenario',
    label: 'Scenarios',
    icon: PlayCircle,
    activePrefixes: ['/scenario', '/runs'],
  },
  {
    path: '/rates',
    label: 'Rates',
    icon: ScrollText,
    activePrefixes: ['/rates'],
  },
  {
    path: '/data-editor',
    label: 'Inputs',
    icon: Table2,
    activePrefixes: ['/data-editor'],
  },
]

const NEW_SCENARIO_VALUE = '__new__'

export function Layout({ children }: { children: ReactNode }) {
  const location = useLocation()
  const isNetworkLevel = location.pathname.startsWith('/network')
  const scenarioMatch = location.pathname.match(
    /^\/network\/scenarios\/([^/]+)(?:\/([^/]+))?/,
  )
  const activeScenarioId = scenarioMatch?.[1] ?? null
  const isDcLevel = location.pathname.startsWith('/dc/')
  const isRouteOptimizerLevel =
    location.pathname.startsWith('/analyze') ||
    location.pathname.startsWith('/scenario') ||
    location.pathname.startsWith('/rates') ||
    location.pathname.startsWith('/data-editor')
  const routeFacility = useRouteContext((state) => state.facility)
  const storedParent = useRouteContext((state) => state.parent)
  const setParent = useRouteContext((state) => state.setParent)
  const urlParent = readParentRouteContext(new URLSearchParams(location.search))
  const parentContext = urlParent.networkScenario ? urlParent : storedParent
  const networkHref = parentContext.networkReturn ?? '/network'
  const depotTabHref =
    routeFacility.facilityType === 'depot'
      ? buildRouteWorkspaceHref('/analyze', parentContext, { depot: routeFacility.facilityId })
      : buildRouteWorkspaceHref('/analyze', parentContext)

  useEffect(() => {
    if (urlParent.networkScenario) setParent(urlParent)
  }, [location.search, setParent])

  return (
    <div className="min-h-screen flex flex-col bg-background">
      <nav className="sticky top-0 z-50 border-b border-border/60 bg-card/80 backdrop-blur">
        <div className="grid min-h-16 grid-cols-[minmax(0,1fr)_auto_minmax(0,1fr)] items-center gap-2 px-4 sm:px-6 lg:px-8">
          <div className="flex min-w-0 items-center gap-1 justify-self-start">
            {activeScenarioId ? (
              <>
                <NavLink
                  to="/network"
                  className="flex shrink-0 items-center gap-2 rounded-md px-2 py-1.5 text-sm font-medium text-muted-foreground transition-colors hover:bg-accent hover:text-foreground md:px-3"
                >
                  <ArrowLeft className="h-4 w-4 text-muted-foreground" />
                  <Network className="hidden h-4 w-4 md:block" />
                  <span className="hidden md:inline">Network</span>
                </NavLink>
                <NetworkScenarioPicker activeScenarioId={activeScenarioId} />
              </>
            ) : isRouteOptimizerLevel || isDcLevel ? (
              <>
                <NavLink
                  to={networkHref}
                  className="flex shrink-0 items-center gap-2 rounded-md px-2 py-1.5 text-sm font-medium text-muted-foreground transition-colors hover:bg-accent hover:text-foreground md:px-3"
                >
                  <ArrowLeft className="h-4 w-4 text-muted-foreground" />
                  <Network className="hidden h-4 w-4 md:block" />
                  <span className="hidden md:inline">Network</span>
                </NavLink>
                <FacilityContextPicker />
              </>
            ) : (
              <Link to="/network" className="flex min-w-0 items-center gap-2">
                <div className="rounded-md bg-primary/15 p-1.5 text-primary">
                  <Route className="h-4 w-4" />
                </div>
                <div className="hidden flex-col leading-tight sm:flex">
                  <span className="text-sm font-semibold tracking-wide">
                    Route Scenario
                  </span>
                  <span className="text-[10px] uppercase tracking-[0.18em] text-muted-foreground">
                    Modeling
                  </span>
                </div>
              </Link>
            )}
          </div>

          <div className="flex min-w-0 items-center gap-1 justify-self-center">
            {isNetworkLevel ? (
              <>
                {!activeScenarioId && (
                  <>
                <NavLink
                  to="/network"
                  className={({ isActive }) =>
                    cn(
                      'flex shrink-0 items-center gap-2 rounded-md px-2 py-1.5 text-sm font-medium transition-colors md:px-3',
                      isActive && !activeScenarioId
                        ? 'bg-primary/15 text-primary'
                        : 'text-muted-foreground hover:bg-accent hover:text-foreground',
                    )
                  }
                >
                  <Network className="h-4 w-4" />
                  <span className="hidden md:inline">Network</span>
                </NavLink>
                <NetworkScenarioPicker activeScenarioId={activeScenarioId} />
                  </>
                )}
                {activeScenarioId &&
                  scenarioTabs.map((tab) => (
                    <NavLink
                      key={tab.id}
                      to={{
                        pathname: `/network/scenarios/${encodeURIComponent(activeScenarioId)}/${tab.id}`,
                        search: location.search,
                      }}
                      className={({ isActive }) =>
                        cn(
                          'hidden shrink-0 items-center gap-2 rounded-md px-2 py-1.5 text-sm font-medium transition-colors md:flex md:px-3',
                          isActive
                            ? 'bg-primary/15 text-primary'
                            : 'text-muted-foreground hover:bg-accent hover:text-foreground',
                        )
                      }
                    >
                      {tab.label}
                    </NavLink>
                  ))}
              </>
            ) : isDcLevel ? null : (
              lowerLevelItems.map((item) => {
                const Icon = item.icon
                const isActive = item.activePrefixes.some((prefix) =>
                  location.pathname.startsWith(prefix),
                )
                const href = item.path === '/analyze'
                  ? depotTabHref
                  : buildRouteWorkspaceHref(item.path, parentContext)
                return (
                  <Link
                    key={item.path}
                    to={href}
                    className={cn(
                      'flex shrink-0 items-center gap-2 rounded-md px-2 py-1.5 text-sm font-medium transition-colors md:px-3',
                      isActive
                        ? 'bg-primary/15 text-primary'
                        : 'text-muted-foreground hover:bg-accent hover:text-foreground',
                    )}
                  >
                    <Icon className="h-4 w-4" />
                    <span className="hidden md:inline">{item.label}</span>
                  </Link>
                )
              })
            )}
          </div>

          <div className="flex min-w-0 items-center justify-self-end gap-2 text-xs text-muted-foreground">
            <NavLink
              to="/setup"
              aria-label="Setup and readiness"
              className={({ isActive }) => cn('rounded-md p-2 hover:bg-accent hover:text-foreground', isActive && 'bg-primary/15 text-primary')}
            >
              <Settings className="h-4 w-4" />
            </NavLink>
            <DemoFreshnessControl />
          </div>
        </div>
      </nav>

      <main className="flex-1 flex flex-col min-h-0">{children}</main>
    </div>
  )
}

function DemoFreshnessControl() {
  const client = useQueryClient()
  const [confirmReset, setConfirmReset] = useState(false)
  const resetButtonRef = useRef<HTMLButtonElement>(null)
  const dialogRef = useRef<HTMLDivElement>(null)
  const resetPendingRef = useRef(false)
  const date = new Date().toLocaleDateString(undefined, {
    month: 'short',
    day: 'numeric',
    year: 'numeric',
  })
  const reset = useMutation({
    mutationFn: api.resetNetworkBaseline,
    onSuccess: async () => {
      await client.invalidateQueries()
      setConfirmReset(false)
    },
  })
  const resetStatus = useQuery({
    queryKey: ['network-reset-status'],
    queryFn: api.resetNetworkBaselineStatus,
    enabled: confirmReset,
    refetchInterval: reset.isPending ? 2_000 : false,
  })
  resetPendingRef.current = reset.isPending

  useEffect(() => {
    if (!confirmReset) return
    const dialog = dialogRef.current
    if (!dialog) return
    const focusableSelector = 'button:not(:disabled), [href], input:not(:disabled), select:not(:disabled), textarea:not(:disabled), [tabindex]:not([tabindex="-1"])'
    const focusable = () => Array.from(dialog.querySelectorAll<HTMLElement>(focusableSelector))
    const frame = requestAnimationFrame(() => focusable().at(-1)?.focus())
    const handleKeyDown = (event: KeyboardEvent) => {
      if (event.key === 'Escape' && !resetPendingRef.current) {
        event.preventDefault()
        setConfirmReset(false)
        return
      }
      if (event.key !== 'Tab') return
      const elements = focusable()
      if (!elements.length) return
      const first = elements[0]
      const last = elements[elements.length - 1]
      if (event.shiftKey && document.activeElement === first) {
        event.preventDefault()
        last.focus()
      } else if (!event.shiftKey && document.activeElement === last) {
        event.preventDefault()
        first.focus()
      }
    }
    document.addEventListener('keydown', handleKeyDown)
    return () => {
      cancelAnimationFrame(frame)
      document.removeEventListener('keydown', handleKeyDown)
      resetButtonRef.current?.focus()
    }
  }, [confirmReset])

  return (
    <>
      <button
        ref={resetButtonRef}
        type="button"
        aria-label={`Demo data as of ${date}. Reset demo`}
        className="flex items-center gap-2 rounded-md px-2 py-1.5 hover:bg-accent hover:text-foreground"
        onClick={() => {
          reset.reset()
          setConfirmReset(true)
        }}
      >
        <span className="h-2 w-2 rounded-full bg-emerald-400 animate-pulse-dot" />
        <span className="hidden lg:inline">As of {date}</span>
      </button>
      {confirmReset && createPortal(
        <div className="fixed inset-0 z-[60] flex items-start justify-center overflow-y-auto bg-black/60 p-2 sm:items-center sm:p-4" role="presentation">
          <div
            ref={dialogRef}
            role="dialog"
            aria-modal="true"
            aria-labelledby="reset-demo-title"
            aria-describedby="reset-demo-description"
            className="flex max-h-[calc(100dvh-1rem)] w-full max-w-md flex-col overflow-hidden rounded-lg border border-border bg-card text-foreground shadow-2xl sm:max-h-[calc(100dvh-2rem)]"
          >
            <div className="shrink-0 border-b border-border px-5 py-4">
              <h2 id="reset-demo-title" className="text-base font-semibold">Reset demo data?</h2>
              <p id="reset-demo-description" className="mt-1 text-sm text-muted-foreground">
                Restore generated data and remove prior network scenarios and depot plans? This cannot be undone.
              </p>
            </div>
            <div className="min-h-0 flex-1 space-y-3 overflow-y-auto px-5 py-4" aria-live="polite">
              {reset.isPending && (
                <p className="text-sm text-muted-foreground">
                  Reset: {resetStatus.data?.reset.state ?? 'starting'} · solver: {resetStatus.data?.solver_warmup.state ?? 'not started'}.
                  {' '}This updates automatically and controls remain disabled until reset finishes.
                </p>
              )}
              {reset.error && <p role="alert" className="text-sm text-destructive">{String(reset.error)}</p>}
            </div>
            <div className="flex shrink-0 justify-end gap-2 border-t border-border px-5 py-4">
              <button
                type="button"
                disabled={reset.isPending}
                className="rounded-md border border-border px-3 py-2 text-sm disabled:opacity-50"
                onClick={() => {
                  reset.reset()
                  setConfirmReset(false)
                }}
              >
                Cancel
              </button>
              <button
                type="button"
                disabled={reset.isPending}
                className="inline-flex items-center gap-2 rounded-md bg-destructive px-3 py-2 text-sm font-semibold text-destructive-foreground disabled:opacity-50"
                onClick={() => reset.mutate()}
              >
                {reset.isPending && <Loader2 className="h-4 w-4 animate-spin" />}
                {reset.isPending ? 'Resetting and warming resources…' : reset.isError ? 'Try reset again' : 'Yes, reset demo'}
              </button>
            </div>
          </div>
        </div>,
        document.body,
      )}
    </>
  )
}

function NetworkScenarioPicker({ activeScenarioId }: { activeScenarioId: string | null }) {
  const navigate = useNavigate()
  const scenarios = useNetworkScenarios()
  const options = useNetworkOptions()
  const createScenario = useCreateNetworkScenario()
  const [error, setError] = useState<string | null>(null)
  const creating = createScenario.isPending
  const baseline = useQuery({
    queryKey: ['network-baseline'],
    queryFn: api.networkBaseline,
  })
  const baselineScenarioId = baseline.data?.active_plan_scenario_id ?? null
  const activeBaselineScenarioId = activeScenarioId?.startsWith('baseline-plan-scenario.')
    ? activeScenarioId
    : null

  async function handleSelect(value: string) {
    setError(null)
    if (value === activeScenarioId) return
    if (value !== NEW_SCENARIO_VALUE) {
      navigate(`/network/scenarios/${encodeURIComponent(value)}/${value === baselineScenarioId ? 'flow' : 'scenario'}`)
      return
    }
    if (!options.data) return
    try {
      const created = await createScenario.mutateAsync({
        scenario_name: 'New network plan',
        demand_plan_version_id: options.data.default_demand_plan_version_id,
        capacity_plan_version_id: options.data.default_capacity_plan_version_id,
        horizon_start: options.data.default_horizon_start,
        horizon_end: options.data.default_horizon_end,
        region_id: options.data.default_region_id,
      })
      navigate(`/network/scenarios/${created.scenario_id}/scenario?rename=1`)
    } catch (err) {
      setError(String(err))
    }
  }

  return (
    <div className="mx-1.5 flex min-w-0 items-center gap-1.5">
      <select
        aria-label="Network scenario"
        value={activeScenarioId ?? ''}
        onChange={(event) => void handleSelect(event.target.value)}
        disabled={scenarios.isLoading || creating}
        className="h-8 max-w-44 truncate rounded-md border border-border bg-background px-2 text-sm font-medium text-foreground disabled:opacity-50"
      >
        <option value="" disabled>
          {scenarios.isLoading ? 'Loading…' : 'Select scenario'}
        </option>
        {baselineScenarioId && (
          <option value={baselineScenarioId}>Published baseline · solved</option>
        )}
        {activeBaselineScenarioId && activeBaselineScenarioId !== baselineScenarioId && (
          <option value={activeBaselineScenarioId}>Published baseline · selected horizon</option>
        )}
        {scenarios.data?.map((scenario) => (
          <option key={scenario.scenario_id} value={scenario.scenario_id}>
            {scenario.scenario_name} · {scenario.status}
          </option>
        ))}
        <option value={NEW_SCENARIO_VALUE}>+ New scenario…</option>
      </select>
      {creating && <Loader2 className="h-3.5 w-3.5 animate-spin text-muted-foreground" />}
      {error && <span className="max-w-40 truncate text-xs text-destructive">{error}</span>}
    </div>
  )
}

function FacilityContextPicker() {
  const location = useLocation()
  const navigate = useNavigate()
  const depots = useDepots()
  const options = useNetworkOptions()
  const facility = useRouteContext((state) => state.facility)
  const setFacility = useRouteContext((state) => state.setFacility)
  const setDepotDay = useScenarioDraft((state) => state.setDepotDay)
  const dcId = location.pathname.match(/^\/dc\/([^/]+)/)?.[1] ?? null
  const isAnalyzeLevel = location.pathname.startsWith('/analyze')
  const isScenarioLevel = location.pathname.startsWith('/scenario')
  const search = new URLSearchParams(location.search)
  const urlDepotId = isAnalyzeLevel ? search.get('depot') : null

  const dcContext = useMemo<NetworkOverviewParams | null>(
    () =>
      dcId && options.data
        ? {
            demand_plan_version_id: options.data.default_demand_plan_version_id,
            capacity_plan_version_id: options.data.default_capacity_plan_version_id,
            horizon_start: options.data.default_horizon_start,
            horizon_end: options.data.default_horizon_end,
            region_id: 'ALL',
            lane_type: 'LINEHAUL',
            metric: 'assigned_flow',
          }
        : null,
    [dcId, options.data],
  )
  const dcOverview = useNetworkOverview(dcContext)
  const activeDc = dcOverview.data?.facilities.find(
    (row) => row.facility_id === dcId && row.facility_type === 'distribution_center',
  )

  function handleSelectDepot(depotId: string) {
    if (facility.facilityId === depotId && facility.facilityType === 'depot') return
    const depot = depots.data?.find((row) => row.depot_id === depotId)
    setFacility({
      facilityId: depotId,
      facilityName: depot?.name ?? depotId,
      facilityType: 'depot',
    })
    if (isScenarioLevel) {
      setDepotDay(depotId, useScenarioDraft.getState().delivery_day)
      return
    }
    const next = new URLSearchParams(location.search)
    next.set('depot', depotId)
    navigate({ pathname: '/analyze', search: next.toString() })
  }

  if (dcId) {
    const name = activeDc?.facility_name ?? facility.facilityName ?? dcId
    return (
      <div className="mx-1.5 flex min-w-0 items-center gap-1.5">
        <span className="flex h-8 min-w-0 items-center gap-1.5 rounded-md border border-primary/40 bg-primary/10 px-2 text-sm font-medium text-primary">
          <Warehouse className="h-3.5 w-3.5 shrink-0" />
          <span className="max-w-48 truncate">{name}</span>
        </span>
      </div>
    )
  }

  const activeDepotId =
    urlDepotId ?? (facility.facilityType === 'depot' ? facility.facilityId : 'DPT_NORTH')

  return (
    <div className="mx-1.5 flex min-w-0 items-center gap-1.5">
      <select
        aria-label="Depot"
        value={activeDepotId}
        onChange={(event) => handleSelectDepot(event.target.value)}
        disabled={depots.isLoading}
        className="h-8 max-w-48 truncate rounded-md border border-border bg-background px-2 text-sm font-medium text-foreground disabled:opacity-50"
      >
        {!depots.data?.some((depot) => depot.depot_id === activeDepotId) && (
          <option value={activeDepotId}>{activeDepotId}</option>
        )}
        {depots.data?.map((depot) => (
          <option key={depot.depot_id} value={depot.depot_id}>
            {depot.name}
          </option>
        ))}
      </select>
    </div>
  )
}
