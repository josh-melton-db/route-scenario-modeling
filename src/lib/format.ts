export function formatNumber(value: number, maximumFractionDigits = 0): string {
  return value.toLocaleString(undefined, { maximumFractionDigits })
}

export function formatCurrency(value: number): string {
  return value.toLocaleString(undefined, {
    style: 'currency',
    currency: 'USD',
    maximumFractionDigits: 0,
  })
}

export function formatPercent(value: number): string {
  return `${formatNumber(value, 1)}%`
}

export function formatMinutes(minutes: number): string {
  const hours = Math.floor(minutes / 60)
  const remaining = Math.abs(minutes % 60)
  if (hours === 0) return `${minutes}m`
  return `${hours}h ${remaining.toString().padStart(2, '0')}m`
}

export function formatDelta(value: number, suffix = ''): string {
  if (value === 0) return `0${suffix}`
  return `${value > 0 ? '+' : ''}${formatNumber(value, 1)}${suffix}`
}
