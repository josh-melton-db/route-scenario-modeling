import { useEffect, useMemo, useRef, useState } from 'react'
import { Check, ChevronsUpDown, Search } from 'lucide-react'
import { cn } from '@/lib/utils'

export interface ScenarioComboboxOption {
  scenario_id: string
  scenario_name: string
}

export default function ScenarioCombobox({
  label,
  value,
  scenarios,
  onChange,
  placeholder = 'Select a scenario',
  includeBaseline = false,
  excludedScenarioId,
  clearLabel = 'Clear comparison',
  allowClear = !includeBaseline,
}: {
  label: string
  value: string
  scenarios: ScenarioComboboxOption[]
  onChange: (value: string) => void
  placeholder?: string
  includeBaseline?: boolean
  excludedScenarioId?: string
  clearLabel?: string
  allowClear?: boolean
}) {
  const [open, setOpen] = useState(false)
  const [query, setQuery] = useState('')
  const rootRef = useRef<HTMLDivElement>(null)
  const inputRef = useRef<HTMLInputElement>(null)

  const options = useMemo(() => {
    const available = scenarios.filter(
      (scenario) =>
        scenario.scenario_id !== 'baseline' &&
        scenario.scenario_id !== excludedScenarioId,
    )
    return includeBaseline
      ? [{ scenario_id: 'baseline', scenario_name: 'Baseline' }, ...available]
      : available
  }, [excludedScenarioId, includeBaseline, scenarios])

  const selected = options.find((option) => option.scenario_id === value)
  const filtered = options.filter((option) =>
    option.scenario_name.toLowerCase().includes(query.trim().toLowerCase()),
  )

  useEffect(() => {
    function handlePointerDown(event: MouseEvent) {
      if (!rootRef.current?.contains(event.target as Node)) setOpen(false)
    }
    document.addEventListener('mousedown', handlePointerDown)
    return () => document.removeEventListener('mousedown', handlePointerDown)
  }, [])

  useEffect(() => {
    if (open) requestAnimationFrame(() => inputRef.current?.focus())
    else setQuery('')
  }, [open])

  return (
    <div ref={rootRef} className="relative min-w-[220px]">
      <div className="mb-1 text-xs font-medium text-muted-foreground">{label}</div>
      <button
        type="button"
        aria-haspopup="listbox"
        aria-expanded={open}
        onClick={() => setOpen((current) => !current)}
        className="flex w-full items-center justify-between gap-3 rounded-md border border-border bg-card px-3 py-2 text-left text-sm shadow-sm transition-colors hover:bg-accent/50 focus:outline-none focus:ring-2 focus:ring-ring/50"
      >
        <span className={cn('truncate', !selected && 'text-muted-foreground')}>
          {selected?.scenario_name ?? placeholder}
        </span>
        <ChevronsUpDown className="h-4 w-4 shrink-0 text-muted-foreground" />
      </button>

      {open && (
        <div className="absolute left-0 top-full z-50 mt-1 w-[min(340px,calc(100vw-2rem))] overflow-hidden rounded-md border border-border bg-popover shadow-xl">
          <div className="flex items-center gap-2 border-b border-border px-3">
            <Search className="h-4 w-4 shrink-0 text-muted-foreground" />
            <input
              ref={inputRef}
              value={query}
              onChange={(event) => setQuery(event.target.value)}
              onKeyDown={(event) => {
                if (event.key === 'Escape') setOpen(false)
                if (event.key === 'Enter' && filtered.length === 1) {
                  onChange(filtered[0].scenario_id)
                  setOpen(false)
                }
              }}
              placeholder="Type to filter scenarios…"
              className="h-10 min-w-0 flex-1 bg-transparent text-sm text-foreground outline-none placeholder:text-muted-foreground"
            />
          </div>
          <div role="listbox" className="max-h-72 overflow-y-auto p-1.5">
            {allowClear && value && !query && (
              <button
                type="button"
                onClick={() => {
                  onChange('')
                  setOpen(false)
                }}
                className="w-full rounded-sm px-2.5 py-2 text-left text-sm text-muted-foreground hover:bg-accent"
              >
                {clearLabel}
              </button>
            )}
            {filtered.map((option) => (
              <button
                type="button"
                role="option"
                aria-selected={option.scenario_id === value}
                key={option.scenario_id}
                onClick={() => {
                  onChange(option.scenario_id)
                  setOpen(false)
                }}
                className="flex w-full items-center gap-2 rounded-sm px-2.5 py-2 text-left text-sm hover:bg-accent"
              >
                <Check
                  className={cn(
                    'h-4 w-4 shrink-0 text-primary',
                    option.scenario_id !== value && 'opacity-0',
                  )}
                />
                <span className="truncate">{option.scenario_name}</span>
              </button>
            ))}
            {filtered.length === 0 && (
              <div className="px-3 py-6 text-center text-sm text-muted-foreground">
                No matching scenarios
              </div>
            )}
          </div>
        </div>
      )}
    </div>
  )
}
