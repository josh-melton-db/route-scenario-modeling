import type { ScenarioType, ScenarioTypeSpec } from '@/api/types'
import { cn } from '@/lib/utils'

interface ScenarioTypePickerProps {
  specs: ScenarioTypeSpec[]
  selected: ScenarioType | null
  onSelect: (spec: ScenarioTypeSpec) => void
}

export default function ScenarioTypePicker({
  specs,
  selected,
  onSelect,
}: ScenarioTypePickerProps) {
  return (
    <div className="grid grid-cols-1 gap-3 md:grid-cols-2 xl:grid-cols-3">
      {specs.map((spec) => (
        <button
          key={spec.scenario_type}
          onClick={() => onSelect(spec)}
          className={cn(
            'rounded-lg border bg-card p-4 text-left transition-colors hover:bg-accent/40',
            selected === spec.scenario_type
              ? 'border-primary/70 bg-primary/10'
              : 'border-border',
          )}
        >
          <div className="font-semibold">{spec.label}</div>
          <p className="mt-2 text-sm leading-5 text-muted-foreground">
            {spec.description}
          </p>
          <div className="mt-3 text-[11px] uppercase tracking-wider text-muted-foreground">
            {spec.fields.length === 0
              ? 'No parameters'
              : `${spec.fields.length} parameters`}
          </div>
        </button>
      ))}
    </div>
  )
}
