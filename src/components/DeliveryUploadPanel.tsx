import { useState } from 'react'
import { Download, Upload } from 'lucide-react'
import { useUploadDeliveries } from '@/api/queries'
import type { DeliveryDraft, DeliveryUploadResult } from '@/api/types'

interface DeliveryUploadPanelProps {
  onConfirm: (deliveries: DeliveryDraft[]) => void
}

export default function DeliveryUploadPanel({
  onConfirm,
}: DeliveryUploadPanelProps) {
  const upload = useUploadDeliveries()
  const [result, setResult] = useState<DeliveryUploadResult | null>(null)
  const [error, setError] = useState<string | null>(null)

  async function handleFile(file: File | null) {
    if (!file) return
    setError(null)
    try {
      const parsed = await upload.mutateAsync(file)
      setResult(parsed)
    } catch (err) {
      setError(String(err))
      setResult(null)
    }
  }

  return (
    <div className="rounded-lg border border-border bg-card p-4">
      <div className="flex flex-wrap items-center justify-between gap-2">
        <div>
          <div className="text-sm font-semibold">Upload Excel deliveries</div>
          <p className="mt-1 text-xs text-muted-foreground">
            Coordinates required (lat/lng). Download the template for the expected columns.
          </p>
        </div>
        <a
          href="/api/scenarios/uploads/template"
          className="inline-flex items-center gap-1 rounded-md border border-border px-2 py-1.5 text-xs"
        >
          <Download className="h-3.5 w-3.5" />
          Template
        </a>
      </div>

      <label className="mt-4 flex cursor-pointer flex-col items-center justify-center gap-2 rounded-md border border-dashed border-border bg-background/40 px-4 py-6 text-sm text-muted-foreground hover:bg-accent/30">
        <Upload className="h-4 w-4" />
        <span>{upload.isPending ? 'Parsing…' : 'Choose .xlsx file'}</span>
        <input
          type="file"
          accept=".xlsx,.xlsm"
          className="hidden"
          onChange={(event) => handleFile(event.target.files?.[0] ?? null)}
        />
      </label>

      {error && (
        <div className="mt-3 rounded-md border border-destructive/40 bg-destructive/10 p-2 text-xs text-destructive">
          {error}
        </div>
      )}

      {result && (
        <div className="mt-3 space-y-2 text-sm">
          <div className="text-xs text-muted-foreground">
            Parsed {result.deliveries.length} deliver
            {result.deliveries.length === 1 ? 'y' : 'ies'}
            {result.errors.length > 0
              ? ` · ${result.errors.length} row error(s)`
              : ''}
          </div>
          {result.errors.length > 0 && (
            <ul className="max-h-28 overflow-auto rounded-md border border-amber-500/30 bg-amber-500/10 p-2 text-xs text-amber-100">
              {result.errors.map((row) => (
                <li key={`${row.row}-${row.message}`}>
                  Row {row.row}: {row.message}
                </li>
              ))}
            </ul>
          )}
          {result.deliveries.length > 0 && (
            <>
              <div className="max-h-36 overflow-auto rounded-md border border-border">
                <table className="w-full text-left text-xs">
                  <thead className="bg-muted/40 text-muted-foreground">
                    <tr>
                      <th className="px-2 py-1">Name</th>
                      <th className="px-2 py-1">Lat</th>
                      <th className="px-2 py-1">Lng</th>
                      <th className="px-2 py-1">Cases</th>
                    </tr>
                  </thead>
                  <tbody>
                    {result.deliveries.slice(0, 8).map((row) => (
                      <tr key={`${row.customer_name}-${row.lat}-${row.lng}`} className="border-t border-border/60">
                        <td className="px-2 py-1">{row.customer_name}</td>
                        <td className="px-2 py-1">{row.lat.toFixed(4)}</td>
                        <td className="px-2 py-1">{row.lng.toFixed(4)}</td>
                        <td className="px-2 py-1">{row.demand_cases}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
              <button
                type="button"
                className="rounded-md bg-primary px-3 py-1.5 text-xs font-semibold text-primary-foreground"
                onClick={() => onConfirm(result.deliveries)}
              >
                Add {result.deliveries.length} deliveries to scenario
              </button>
            </>
          )}
        </div>
      )}
    </div>
  )
}
