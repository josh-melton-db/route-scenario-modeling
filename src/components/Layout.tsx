import { Link, useLocation } from 'react-router-dom'
import { BarChart3, MapPinned, PlayCircle, Route, Table2 } from 'lucide-react'
import type { ReactNode } from 'react'
import { cn } from '@/lib/utils'

const navItems = [
  {
    path: '/baseline',
    label: 'Analyze',
    icon: MapPinned,
    activePrefixes: ['/baseline', '/comparison'],
  },
  {
    path: '/scenario',
    label: 'Scenario Builder',
    icon: PlayCircle,
    activePrefixes: ['/scenario', '/runs'],
  },
  {
    path: '/data-editor',
    label: 'Data editor',
    icon: Table2,
    activePrefixes: ['/data-editor'],
  },
]

export function Layout({ children }: { children: ReactNode }) {
  const location = useLocation()

  return (
    <div className="min-h-screen flex flex-col bg-background">
      <nav className="sticky top-0 z-50 border-b border-border/60 bg-card/80 backdrop-blur">
        <div className="grid min-h-16 grid-cols-[minmax(0,1fr)_auto_minmax(0,1fr)] items-center gap-2 px-4 sm:px-6 lg:px-8">
          <Link to="/baseline" className="flex min-w-0 items-center gap-2 justify-self-start">
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

          <div className="flex items-center gap-1 justify-self-center">
            {navItems.map((item) => {
              const Icon = item.icon
              const isActive = item.activePrefixes.some((prefix) =>
                location.pathname.startsWith(prefix),
              )
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
