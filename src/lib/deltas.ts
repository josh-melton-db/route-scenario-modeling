export type DeltaTone = 'good' | 'bad' | 'neutral'

const LOWER_IS_BETTER = new Set([
  'total_miles',
  'drive_minutes',
  'overtime_minutes',
  'missed_windows',
  'late_minutes',
  'mileage_cost',
  'labor_cost',
  'overtime_cost',
  'fixed_vehicle_cost',
  'sla_penalty_cost',
  'total_cost',
])

export function deltaTone(metric: string, value: number): DeltaTone {
  if (value === 0) return 'neutral'
  if (!LOWER_IS_BETTER.has(metric)) return 'neutral'
  return value < 0 ? 'good' : 'bad'
}
