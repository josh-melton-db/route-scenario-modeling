import { Loader2, Plus, Save, Trash2 } from 'lucide-react'
import { useEffect, useMemo, useState } from 'react'
import type { EditorEntityType, EditorRow } from '@/api/types'

type EditorInputKind = 'text' | 'number' | 'date'

export interface EditorColumn {
  key: string
  label: string
  input: EditorInputKind
  required?: boolean
  step?: string
}

export interface EditorTableDefinition {
  label: string
  singularLabel: string
  description: string
  columns: EditorColumn[]
}

export const dataEditorTables: Record<EditorEntityType, EditorTableDefinition> = {
  orders: {
    label: 'Delivery orders',
    singularLabel: 'delivery order',
    description: 'Demand and planned delivery-day inputs used to reconstruct routes.',
    columns: [
      { key: 'order_id', label: 'Order ID', input: 'text', required: true },
      { key: 'customer_id', label: 'Customer ID', input: 'text', required: true },
      { key: 'depot_id', label: 'Depot ID', input: 'text', required: true },
      { key: 'delivery_day', label: 'Delivery day', input: 'text', required: true },
      { key: 'route_date', label: 'Route date', input: 'date' },
      { key: 'demand_cases', label: 'Cases', input: 'number', required: true, step: '1' },
      { key: 'product_family', label: 'Product family', input: 'text' },
    ],
  },
  customers: {
    label: 'Customers',
    singularLabel: 'customer',
    description: 'Service locations, delivery cadence, and receiving constraints.',
    columns: [
      { key: 'customer_id', label: 'Customer ID', input: 'text', required: true },
      { key: 'customer_name', label: 'Customer name', input: 'text', required: true },
      { key: 'depot_id', label: 'Depot ID', input: 'text', required: true },
      { key: 'region', label: 'Region', input: 'text', required: true },
      { key: 'sales_territory', label: 'Sales territory', input: 'text', required: true },
      { key: 'lat', label: 'Latitude', input: 'number', required: true, step: '0.000001' },
      { key: 'lng', label: 'Longitude', input: 'number', required: true, step: '0.000001' },
      { key: 'customer_priority', label: 'Priority', input: 'text' },
      { key: 'delivery_frequency', label: 'Frequency', input: 'number', step: '1' },
      { key: 'eligible_delivery_days', label: 'Eligible days', input: 'text', required: true },
      { key: 'receiving_window_start', label: 'Window start', input: 'text', required: true },
      { key: 'receiving_window_end', label: 'Window end', input: 'text', required: true },
      { key: 'service_minutes', label: 'Service min.', input: 'number', required: true, step: '1' },
      { key: 'special_handling', label: 'Special handling', input: 'text' },
    ],
  },
  fleet: {
    label: 'Fleet',
    singularLabel: 'vehicle',
    description: 'Vehicle availability, capacity, and vehicle-specific operating inputs.',
    columns: [
      { key: 'vehicle_id', label: 'Vehicle ID', input: 'text', required: true },
      { key: 'depot_id', label: 'Depot ID', input: 'text', required: true },
      { key: 'vehicle_type', label: 'Vehicle type', input: 'text' },
      { key: 'capacity_cases', label: 'Capacity', input: 'number', required: true, step: '1' },
      { key: 'fixed_truck_daily_cost', label: 'Daily cost', input: 'number', step: '0.01' },
      { key: 'cost_per_mile', label: 'Cost / mile', input: 'number', step: '0.01' },
      { key: 'max_route_minutes', label: 'Max route min.', input: 'number', step: '1' },
      { key: 'available_days', label: 'Available days', input: 'text', required: true },
    ],
  },
  depots: {
    label: 'Depots',
    singularLabel: 'depot',
    description: 'Network origins and geography used for delivery-route reconstruction.',
    columns: [
      { key: 'depot_id', label: 'Depot ID', input: 'text', required: true },
      { key: 'depot_name', label: 'Depot name', input: 'text', required: true },
      { key: 'region', label: 'Region', input: 'text', required: true },
      { key: 'sales_territory', label: 'Sales territory', input: 'text', required: true },
      { key: 'lat', label: 'Latitude', input: 'number', required: true, step: '0.000001' },
      { key: 'lng', label: 'Longitude', input: 'number', required: true, step: '0.000001' },
      { key: 'operating_calendar', label: 'Operating calendar', input: 'text' },
    ],
  },
  cost_parameters: {
    label: 'Cost parameters',
    singularLabel: 'cost parameter set',
    description: 'Shared cost assumptions applied consistently to baseline reconstruction and optimization.',
    columns: [
      { key: 'parameter_set_id', label: 'Parameter set', input: 'text', required: true },
      { key: 'cost_per_mile', label: 'Cost / mile', input: 'number', required: true, step: '0.01' },
      { key: 'labor_regular_hour', label: 'Labor / hour', input: 'number', required: true, step: '0.01' },
      { key: 'overtime_multiplier', label: 'OT multiplier', input: 'number', required: true, step: '0.01' },
      { key: 'overtime_threshold_minutes', label: 'OT threshold', input: 'number', required: true, step: '1' },
      { key: 'fixed_truck_daily_cost', label: 'Daily truck cost', input: 'number', required: true, step: '0.01' },
      { key: 'max_route_minutes', label: 'Max route min.', input: 'number', required: true, step: '1' },
      { key: 'late_delivery_penalty', label: 'Late penalty', input: 'number', required: true, step: '0.01' },
      { key: 'missed_delivery_penalty', label: 'Missed penalty', input: 'number', required: true, step: '0.01' },
      { key: 'avg_speed_mph', label: 'Avg. speed', input: 'number', required: true, step: '0.1' },
      { key: 'circuity', label: 'Circuity', input: 'number', required: true, step: '0.01' },
    ],
  },
}

type DraftRow = Record<string, string>

function initialDraft(columns: EditorColumn[], data?: Record<string, unknown>): DraftRow {
  return Object.fromEntries(
    columns.map((column) => [column.key, String(data?.[column.key] ?? '')]),
  )
}

function valueFromInput(column: EditorColumn, value: string): unknown {
  if (column.input === 'number') {
    return value === '' ? null : Number(value)
  }
  if (column.input === 'date') {
    return value === '' ? null : value
  }
  return value
}

function changesForRow(
  columns: EditorColumn[],
  source: Record<string, unknown>,
  draft: DraftRow,
): Record<string, unknown> {
  return Object.fromEntries(
    columns.flatMap((column) => {
      const next = valueFromInput(column, draft[column.key] ?? '')
      return Object.is(source[column.key], next) ? [] : [[column.key, next]]
    }),
  )
}

function stateLabel(row: EditorRow): string {
  if (row.state === 'inserted') return 'New'
  if (row.state === 'updated') return 'Edited'
  return ''
}

export default function DataEditorTable({
  entityType,
  rows,
  disabled,
  busy,
  onInsert,
  onPatch,
  onDelete,
}: {
  entityType: EditorEntityType
  rows: EditorRow[]
  disabled: boolean
  busy: boolean
  onInsert: (data: Record<string, unknown>) => Promise<void>
  onPatch: (
    rowId: string,
    rowVersion: number,
    changes: Record<string, unknown>,
  ) => Promise<void>
  onDelete: (rowId: string, rowVersion: number) => Promise<void>
}) {
  const table = dataEditorTables[entityType]
  const [drafts, setDrafts] = useState<Record<string, DraftRow>>({})
  const [adding, setAdding] = useState(false)
  const [newRow, setNewRow] = useState<DraftRow>(() => initialDraft(table.columns))

  useEffect(() => {
    setDrafts({})
  }, [entityType, rows])

  const hasRows = rows.length > 0
  const columnCount = table.columns.length + 2
  const newRowData = useMemo(
    () =>
      Object.fromEntries(
        table.columns.map((column) => [
          column.key,
          valueFromInput(column, newRow[column.key] ?? ''),
        ]),
      ),
    [newRow, table.columns],
  )

  async function saveRow(row: EditorRow) {
    const draft = drafts[row.row_id] ?? initialDraft(table.columns, row.data)
    const changes = changesForRow(table.columns, row.data, draft)
    if (Object.keys(changes).length === 0) return
    try {
      await onPatch(row.row_id, row.row_version, changes)
    } catch {
      // The page keeps the draft intact and renders the API error.
      return
    }
  }

  async function saveNewRow() {
    try {
      await onInsert(newRowData)
    } catch {
      // Do not discard the row draft when server-side validation fails.
      return
    }
    setNewRow(initialDraft(table.columns))
    setAdding(false)
  }

  return (
    <div className="overflow-hidden rounded-lg border border-border bg-card">
      <div className="flex flex-wrap items-start justify-between gap-3 border-b border-border p-4">
        <div>
          <h2 className="text-sm font-semibold">{table.label}</h2>
          <p className="mt-1 max-w-3xl text-xs text-muted-foreground">
            {table.description}
          </p>
        </div>
        <button
          type="button"
          disabled={disabled || busy}
          onClick={() => {
            setAdding(true)
            setNewRow(initialDraft(table.columns))
          }}
          className="inline-flex items-center gap-2 rounded-md border border-border px-3 py-2 text-xs font-medium transition-colors hover:bg-accent disabled:cursor-not-allowed disabled:opacity-50"
        >
          <Plus className="h-3.5 w-3.5" />
          Add {table.singularLabel}
        </button>
      </div>

      <div className="overflow-x-auto">
        <table className="min-w-full border-collapse text-left text-xs">
          <thead className="bg-muted/40 text-muted-foreground">
            <tr>
              {table.columns.map((column) => (
                <th key={column.key} className="whitespace-nowrap px-3 py-2 font-medium">
                  {column.label}
                  {column.required ? <span className="ml-0.5 text-primary">*</span> : null}
                </th>
              ))}
              <th className="whitespace-nowrap px-3 py-2 font-medium">State</th>
              <th className="sticky right-0 bg-muted/40 px-3 py-2 text-right font-medium">
                Actions
              </th>
            </tr>
          </thead>
          <tbody>
            {adding ? (
              <tr className="border-t border-border bg-primary/5">
                {table.columns.map((column) => (
                  <td key={column.key} className="p-2">
                    <input
                      aria-label={`New ${column.label}`}
                      type={column.input}
                      step={column.step}
                      value={newRow[column.key] ?? ''}
                      onChange={(event) =>
                        setNewRow((current) => ({
                          ...current,
                          [column.key]: event.target.value,
                        }))
                      }
                      className="min-w-28 rounded border border-border bg-background px-2 py-1.5 text-xs outline-none ring-primary focus:ring-1"
                    />
                  </td>
                ))}
                <td className="px-3 py-2 text-primary">New</td>
                <td className="sticky right-0 bg-primary/5 px-3 py-2">
                  <div className="flex justify-end gap-2">
                    <button
                      type="button"
                      disabled={busy}
                      onClick={() => void saveNewRow()}
                      className="rounded bg-primary px-2 py-1 text-xs font-semibold text-primary-foreground disabled:opacity-50"
                    >
                      Save
                    </button>
                    <button
                      type="button"
                      disabled={busy}
                      onClick={() => setAdding(false)}
                      className="rounded border border-border px-2 py-1 text-xs disabled:opacity-50"
                    >
                      Cancel
                    </button>
                  </div>
                </td>
              </tr>
            ) : null}

            {rows.map((row) => {
              const draft = drafts[row.row_id] ?? initialDraft(table.columns, row.data)
              return (
                <tr key={row.row_id} className="border-t border-border/70">
                  {table.columns.map((column) => (
                    <td key={column.key} className="p-2">
                      <input
                        aria-label={`${row.row_id} ${column.label}`}
                        type={column.input}
                        step={column.step}
                        value={draft[column.key] ?? ''}
                        disabled={disabled || busy || column === table.columns[0]}
                        onChange={(event) =>
                          setDrafts((current) => ({
                            ...current,
                            [row.row_id]: {
                              ...draft,
                              [column.key]: event.target.value,
                            },
                          }))
                        }
                        className="min-w-28 rounded border border-transparent bg-transparent px-2 py-1.5 text-xs outline-none ring-primary hover:border-border focus:border-border focus:bg-background focus:ring-1 disabled:cursor-not-allowed disabled:opacity-60"
                      />
                    </td>
                  ))}
                  <td className="px-3 py-2">
                    {stateLabel(row) ? (
                      <span className="rounded-full bg-primary/15 px-2 py-0.5 text-[10px] font-medium text-primary">
                        {stateLabel(row)}
                      </span>
                    ) : (
                      <span className="text-muted-foreground">—</span>
                    )}
                  </td>
                  <td className="sticky right-0 bg-card px-3 py-2">
                    <div className="flex justify-end gap-1">
                      <button
                        type="button"
                        title="Save row"
                        aria-label={`Save ${row.row_id}`}
                        disabled={disabled || busy}
                        onClick={() => void saveRow(row)}
                        className="rounded p-1.5 text-primary transition-colors hover:bg-primary/15 disabled:cursor-not-allowed disabled:opacity-50"
                      >
                        {busy ? <Loader2 className="h-3.5 w-3.5 animate-spin" /> : <Save className="h-3.5 w-3.5" />}
                      </button>
                      <button
                        type="button"
                        title="Delete row"
                        aria-label={`Delete ${row.row_id}`}
                        disabled={disabled || busy}
                        onClick={() => {
                          if (
                            window.confirm(
                              `Remove ${row.row_id} from this editor session?`,
                            )
                          ) {
                            void onDelete(row.row_id, row.row_version).catch(() => undefined)
                          }
                        }}
                        className="rounded p-1.5 text-destructive transition-colors hover:bg-destructive/10 disabled:cursor-not-allowed disabled:opacity-50"
                      >
                        <Trash2 className="h-3.5 w-3.5" />
                      </button>
                    </div>
                  </td>
                </tr>
              )
            })}
            {!hasRows && !adding ? (
              <tr>
                <td
                  colSpan={columnCount}
                  className="px-4 py-12 text-center text-sm text-muted-foreground"
                >
                  No {table.label.toLowerCase()} in this editor session.
                </td>
              </tr>
            ) : null}
          </tbody>
        </table>
      </div>
    </div>
  )
}
