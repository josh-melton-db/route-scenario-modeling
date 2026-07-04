import type { LatLng, ParameterField } from '@/api/types'

interface ParameterFormProps {
  fields: ParameterField[]
  values: Record<string, unknown>
  onChange: (name: string, value: unknown) => void
}

export default function ParameterForm({
  fields,
  values,
  onChange,
}: ParameterFormProps) {
  if (fields.length === 0) {
    return (
      <div className="rounded-lg border border-border bg-card p-4 text-sm text-muted-foreground">
        This scenario has no editable parameters.
      </div>
    )
  }

  return (
    <div className="rounded-lg border border-border bg-card p-4">
      <div className="text-sm font-semibold">Scenario parameters</div>
      <div className="mt-4 grid grid-cols-1 gap-4 md:grid-cols-2">
        {fields.map((field) => (
          <FieldControl
            key={field.name}
            field={field}
            value={values[field.name] ?? field.default}
            onChange={(value) => onChange(field.name, value)}
          />
        ))}
      </div>
    </div>
  )
}

function FieldControl({
  field,
  value,
  onChange,
}: {
  field: ParameterField
  value: unknown
  onChange: (value: unknown) => void
}) {
  return (
    <label className="flex flex-col gap-1.5 text-sm">
      <span className="font-medium">
        {field.label}
        {field.required && <span className="text-primary"> *</span>}
      </span>
      {renderInput(field, value, onChange)}
      {field.help_text && (
        <span className="text-xs leading-5 text-muted-foreground">
          {field.help_text}
        </span>
      )}
    </label>
  )
}

function renderInput(
  field: ParameterField,
  value: unknown,
  onChange: (value: unknown) => void,
) {
  const inputClass =
    'rounded-md border border-border bg-background px-3 py-2 text-sm text-foreground'

  if (field.field_type === 'select') {
    return (
      <select
        value={String(value ?? '')}
        onChange={(event) => onChange(event.target.value)}
        className={inputClass}
      >
        {field.options.map((option) => (
          <option key={option.value} value={option.value}>
            {option.label}
          </option>
        ))}
      </select>
    )
  }

  if (field.field_type === 'boolean') {
    return (
      <select
        value={String(Boolean(value))}
        onChange={(event) => onChange(event.target.value === 'true')}
        className={inputClass}
      >
        <option value="true">Yes</option>
        <option value="false">No</option>
      </select>
    )
  }

  if (field.field_type === 'latlng') {
    const latLng = isLatLng(value) ? value : undefined
    const display =
      latLng !== undefined ? `${latLng.lat}, ${latLng.lng}` : String(value ?? '')
    return (
      <input
        value={display}
        placeholder={field.placeholder ?? 'lat, lng'}
        onChange={(event) => onChange(parseLatLng(event.target.value))}
        className={inputClass}
      />
    )
  }

  if (field.field_type === 'number' || field.field_type === 'integer') {
    return (
      <input
        type="number"
        value={Number(value ?? 0)}
        min={field.min ?? undefined}
        max={field.max ?? undefined}
        step={field.step ?? (field.field_type === 'integer' ? 1 : undefined)}
        onChange={(event) =>
          onChange(
            field.field_type === 'integer'
              ? Number.parseInt(event.target.value, 10)
              : Number.parseFloat(event.target.value),
          )
        }
        className={inputClass}
      />
    )
  }

  return (
    <input
      value={String(value ?? '')}
      placeholder={field.placeholder ?? undefined}
      onChange={(event) => onChange(event.target.value)}
      className={inputClass}
    />
  )
}

function isLatLng(value: unknown): value is LatLng {
  return (
    typeof value === 'object' &&
    value !== null &&
    'lat' in value &&
    'lng' in value
  )
}

function parseLatLng(value: string): LatLng | string {
  const [rawLat, rawLng] = value.split(',').map((part) => part.trim())
  const lat = Number.parseFloat(rawLat)
  const lng = Number.parseFloat(rawLng)
  if (Number.isFinite(lat) && Number.isFinite(lng)) {
    return { lat, lng }
  }
  return value
}
