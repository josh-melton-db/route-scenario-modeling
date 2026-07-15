import { Link, useLocation } from 'react-router-dom'
import { BarChart3, MapPinned, PlayCircle, Route, Table2 } from 'lucide-react'
import type { ReactNode } from 'react'
import { cn } from '@/lib/utils'

const navItems = [
  { path: '/baseline', label: 'Baseline', icon: MapPinned },
  { path: '/scenario', label: 'Scenario Builder', icon: PlayCircle },
  { path: '/data-editor', label: 'Data editor', icon: Table2 },
]

const routeMetadata = [
  {
    matches: (pathname: string) => pathname.startsWith('/baseline'),
    title: 'Baseline network',
    subtitle:
      'Current-state Generic Co delivery routes and route-level operating metrics.',
  },
  {
    matches: (pathname: string) => pathname.startsWith('/scenario'),
    title: 'Scenario builder',
    subtitle:
      'Configure a what-if scenario for Generic Co and launch the served optimization run.',
  },
  {
    matches: (pathname: string) => pathname.startsWith('/data-editor'),
    title: 'Data editor',
    subtitle:
      'Edit session-isolated planning inputs, preview their baseline, then commit or discard.',
  },
  {
    matches: (pathname: string) => pathname.startsWith('/runs/'),
    title: 'Optimization run',
    subtitle: 'Track server-owned precheck and optimization progress.',
  },
  {
    matches: (pathname: string) => pathname.startsWith('/comparison/'),
    title: 'Scenario comparison',
    subtitle: 'Review optimization outcomes against the baseline network.',
  },
]

export function Layout({ children }: { children: ReactNode }) {
  const location = useLocation()
  const metadata =
    routeMetadata.find((route) => route.matches(location.pathname)) ??
    routeMetadata[0]

  return (
    <div className="min-h-screen flex flex-col bg-background">
      <nav className="sticky top-0 z-50 border-b border-border/60 bg-card/80 backdrop-blur">
        <div className="grid min-h-16 grid-cols-[minmax(0,1fr)_minmax(0,12rem)_minmax(0,1fr)] items-center gap-2 px-4 sm:grid-cols-[minmax(0,1fr)_minmax(0,18rem)_minmax(0,1fr)] sm:px-6 xl:grid-cols-[minmax(0,1fr)_minmax(0,32rem)_minmax(0,1fr)] lg:px-8">
          <div className="flex min-w-0 items-center gap-1 overflow-hidden">
            <Link to="/baseline" className="mr-4 hidden shrink-0 items-center gap-2 xl:flex">
              <div className="rounded-md bg-primary/15 p-1.5 text-primary">
                <Route className="h-4 w-4" />
              </div>
              <div className="flex flex-col leading-tight">
                <span className="text-sm font-semibold tracking-wide">
                  Route Scenario
                </span>
                <span className="text-[10px] uppercase tracking-[0.18em] text-muted-foreground">
                  Modeling
                </span>
              </div>
            </Link>

            <div className="flex min-w-0 items-center gap-1">
              {navItems.map((item) => {
                const Icon = item.icon
                const isActive = location.pathname.startsWith(item.path)
                return (
                  <Link
                    key={item.path}
                    to={item.path}
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
              })}
            </div>
          </div>

          <div className="min-w-0 text-center">
            <div className="truncate text-sm font-semibold leading-tight tracking-tight">
              {metadata.title}
            </div>
            <div className="truncate text-[10px] leading-tight text-muted-foreground">
              {metadata.subtitle}
            </div>
          </div>

          <div className="flex min-w-0 items-center justify-self-end gap-2 text-xs text-muted-foreground">
            <BarChart3 className="h-3.5 w-3.5" />
            <span className="h-2 w-2 rounded-full bg-emerald-400 animate-pulse-dot" />
            <span className="hidden 2xl:inline">
              Scenario planning ·{' '}
              {new Date().toLocaleDateString(undefined, {
                month: 'short',
                day: 'numeric',
              })}
            </span>
          </div>
        </div>
      </nav>

      <main className="flex-1 flex flex-col min-h-0">{children}</main>
    </div>
  )
}
