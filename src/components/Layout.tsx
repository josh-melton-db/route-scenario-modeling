import { Link, useLocation } from 'react-router-dom'
import { BarChart3, MapPinned, PlayCircle, Route } from 'lucide-react'
import type { ReactNode } from 'react'
import { cn } from '@/lib/utils'

const navItems = [
  { path: '/baseline', label: 'Baseline', icon: MapPinned },
  { path: '/scenario', label: 'Scenario Builder', icon: PlayCircle },
]

export function Layout({ children }: { children: ReactNode }) {
  const location = useLocation()

  return (
    <div className="min-h-screen flex flex-col bg-background">
      <nav className="sticky top-0 z-50 border-b border-border/60 bg-card/80 backdrop-blur">
        <div className="flex h-14 items-center px-4 sm:px-6 lg:px-8">
          <Link to="/baseline" className="flex items-center gap-2 mr-8">
            <div className="rounded-md bg-primary/15 p-1.5 text-primary">
              <Route className="h-4 w-4" />
            </div>
            <div className="flex flex-col leading-tight">
              <span className="font-semibold tracking-wide text-sm">Route Scenario</span>
              <span className="text-[10px] uppercase tracking-[0.18em] text-muted-foreground">
                Modeling
              </span>
            </div>
          </Link>

          <div className="flex items-center gap-1">
            {navItems.map((item) => {
              const Icon = item.icon
              const isActive = location.pathname.startsWith(item.path)
              return (
                <Link
                  key={item.path}
                  to={item.path}
                  className={cn(
                    'flex items-center gap-2 rounded-md px-3 py-1.5 text-sm font-medium transition-colors',
                    isActive
                      ? 'bg-primary/15 text-primary'
                      : 'text-muted-foreground hover:bg-accent hover:text-foreground',
                  )}
                >
                  <Icon className="h-4 w-4" />
                  <span>{item.label}</span>
                </Link>
              )
            })}
          </div>

          <div className="ml-auto flex items-center gap-2 text-xs text-muted-foreground">
            <BarChart3 className="h-3.5 w-3.5" />
            <span className="h-2 w-2 rounded-full bg-emerald-400 animate-pulse-dot" />
            <span>Scenario planning · {new Date().toLocaleDateString(undefined, { month: 'short', day: 'numeric' })}</span>
          </div>
        </div>
      </nav>

      <main className="flex-1 flex flex-col min-h-0">{children}</main>
    </div>
  )
}
