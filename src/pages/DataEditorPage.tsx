import { useEffect, useMemo, useState } from 'react'
import { useQueryClient } from '@tanstack/react-query'
import {
  AlertTriangle,
  CheckCircle2,
  Eye,
  Loader2,
  RefreshCw,
  Save,
  ShieldCheck,
  Trash2,
} from 'lucide-react'
import DataEditorTable, { dataEditorTables } from '@/components/DataEditorTable'
import ErrorState from '@/components/ErrorState'
import {
  queryKeys,
  useCommitEditorSession,
  useDays,
  useDeleteEditorRow,
  useDepots,
  useDiscardEditorSession,
  useEditorRows,
  useInsertEditorRow,
  useOpenEditorSession,
  usePatchEditorRow,
  usePreviewEditorBaseline,
  useValidateEditorSession,
} from '@/api/queries'
import type {
  EditorEntityType,
  EditorSession,
  EditorValidationResponse,
} from '@/api/types'

const pageSize = 25
const editorEntities: EditorEntityType[] = [
  'orders',
  'customers',
  'fleet',
  'depots',
  'cost_parameters',
]

function messageFor(error: unknown): string {
  return error instanceof Error ? error.message : String(error)
}

function isConflict(error: unknown): boolean {
  return /\b409\b|conflict/i.test(messageFor(error))
}

export default function DataEditorPage() {
  const queryClient = useQueryClient()
  const [session, setSession] = useState<EditorSession | null>(null)
  const [entityType, setEntityType] = useState<EditorEntityType>('orders')
  const [page, setPage] = useState(1)
  const [validation, setValidation] = useState<EditorValidationResponse | null>(null)
  const [actionError, setActionError] = useState<string | null>(null)
  const [conflictMessage, setConflictMessage] = useState<string | null>(null)
  const [previewDepotId, setPreviewDepotId] = useState('DPT_NORTH')
  const [previewDeliveryDay, setPreviewDeliveryDay] = useState('Tuesday')

  const openSession = useOpenEditorSession()
  const insertRow = useInsertEditorRow()
  const patchRow = usePatchEditorRow()
  const deleteRow = useDeleteEditorRow()
  const validateSession = useValidateEditorSession()
  const previewBaseline = usePreviewEditorBaseline()
  const commitSession = useCommitEditorSession()
  const discardSession = useDiscardEditorSession()
  const rows = useEditorRows(session?.session_id, entityType, page, pageSize)
  const depots = useDepots()
  const days = useDays()

  const busy =
    openSession.isPending ||
    insertRow.isPending ||
    patchRow.isPending ||
    deleteRow.isPending ||
    validateSession.isPending ||
    previewBaseline.isPending ||
    commitSession.isPending ||
    discardSession.isPending
  const isOpen = session?.status === 'open'
  const activeTable = dataEditorTables[entityType]
  const total = rows.data?.total ?? 0
  const totalPages = Math.max(1, Math.ceil(total / pageSize))

  useEffect(() => {
    openSession.mutate(undefined, {
      onSuccess: (nextSession) => {
        setSession(nextSession)
        setActionError(null)
      },
      onError: (error) => setActionError(messageFor(error)),
    })
    // The editor creates one isolated snapshot for each page visit.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [])

  useEffect(() => {
    if (rows.data?.session) setSession(rows.data.session)
  }, [rows.data?.session])

  useEffect(() => {
    if (depots.data?.length && !depots.data.some((depot) => depot.depot_id === previewDepotId)) {
      setPreviewDepotId(depots.data[0].depot_id)
    }
  }, [depots.data, previewDepotId])

  useEffect(() => {
    if (days.data?.length && !days.data.includes(previewDeliveryDay)) {
      setPreviewDeliveryDay(days.data[0])
    }
  }, [days.data, previewDeliveryDay])

  const sessionId = session?.session_id
  const pageLabel = useMemo(
    () => `${Math.min(page, totalPages)} of ${totalPages}`,
    [page, totalPages],
  )

  async function refreshCurrentTable() {
    if (!sessionId) return
    await queryClient.invalidateQueries({
      queryKey: queryKeys.editorRows(sessionId, entityType, page, pageSize),
    })
  }

  async function openFreshSession() {
    setActionError(null)
    setConflictMessage(null)
    setValidation(null)
    previewBaseline.reset()
    try {
      const nextSession = await openSession.mutateAsync()
      setSession(nextSession)
      setPage(1)
    } catch (error) {
      setActionError(messageFor(error))
    }
  }

  function recordActionError(error: unknown) {
    const message = messageFor(error)
    if (/\b410\b/.test(message)) {
      setSession((current) =>
        current
          ? { ...current, status: 'expired', has_unsaved_changes: false }
          : current,
      )
      setActionError(message)
    } else if (isConflict(error)) {
      setConflictMessage(message)
    } else {
      setActionError(message)
    }
  }

  async function mutateAndRefresh(action: () => Promise<unknown>) {
    setActionError(null)
    setConflictMessage(null)
    try {
      await action()
      setValidation(null)
      previewBaseline.reset()
      await refreshCurrentTable()
    } catch (error) {
      recordActionError(error)
      throw error
    }
  }

  async function handleValidate() {
    if (!sessionId) return
    setActionError(null)
    setConflictMessage(null)
    try {
      const result = await validateSession.mutateAsync(sessionId)
      setSession(result.session)
      setValidation(result)
    } catch (error) {
      recordActionError(error)
    }
  }

  async function handlePreview() {
    if (!sessionId) return
    setActionError(null)
    setConflictMessage(null)
    try {
      const result = await previewBaseline.mutateAsync({
        sessionId,
        payload: {
          depot_id: previewDepotId,
          delivery_day: previewDeliveryDay,
        },
      })
      setSession(result.session)
      setValidation(null)
    } catch (error) {
      recordActionError(error)
    }
  }

  async function handleCommit() {
    if (!sessionId) return
    setActionError(null)
    setConflictMessage(null)
    try {
      const result = await commitSession.mutateAsync(sessionId)
      setSession(result.session)
      setValidation(null)
      await Promise.all([
        queryClient.invalidateQueries({ queryKey: queryKeys.depots }),
        queryClient.invalidateQueries({ queryKey: queryKeys.days }),
        queryClient.invalidateQueries({ queryKey: ['baseline-network'] }),
        queryClient.invalidateQueries({ queryKey: ['baseline-kpis'] }),
      ])
    } catch (error) {
      recordActionError(error)
    }
  }

  async function handleDiscard() {
    if (!sessionId) return
    setActionError(null)
    setConflictMessage(null)
    try {
      const nextSession = await discardSession.mutateAsync(sessionId)
      setSession(nextSession)
      setValidation(null)
      previewBaseline.reset()
      await refreshCurrentTable()
    } catch (error) {
      recordActionError(error)
    }
  }

  if (!session && (openSession.isPending || !actionError)) {
    return (
      <div className="flex h-full items-center justify-center text-muted-foreground">
        <Loader2 className="mr-2 h-4 w-4 animate-spin" />
        Opening isolated data session...
      </div>
    )
  }

  if (!session) {
    return <ErrorState title="Could not open Data editor" error={actionError} />
  }

  return (
    <div className="flex flex-col gap-5 px-4 py-5 sm:px-6 lg:px-8">
      <section className="rounded-lg border border-border bg-card p-4">
        <div className="flex flex-wrap items-start justify-between gap-4">
          <div className="max-w-3xl">
            <div className="flex items-center gap-2 text-sm font-semibold">
              <ShieldCheck className="h-4 w-4 text-primary" />
              Session-isolated planning data
            </div>
            <p className="mt-1 text-xs leading-5 text-muted-foreground">
              Edits stay in your private Lakebase snapshot until you validate and commit.
              This editor intentionally includes only solver inputs: delivery orders,
              customers, fleet, depots, and cost parameters.
            </p>
          </div>
          <div className="text-right text-xs text-muted-foreground">
            <div className="font-medium capitalize text-foreground">{session.status} session</div>
            <div className="mt-1">
              Expires {new Date(session.expires_at).toLocaleString()}
            </div>
          </div>
        </div>

        {session.has_unsaved_changes && isOpen ? (
          <div className="mt-4 flex items-start gap-2 rounded-md border border-amber-400/35 bg-amber-400/10 p-3 text-xs text-amber-200">
            <AlertTriangle className="mt-0.5 h-4 w-4 flex-shrink-0" />
            <div>
              <span className="font-semibold">Uncommitted changes.</span> Preview or validate
              your snapshot before promoting it to the shared planning baseline.
            </div>
          </div>
        ) : null}
      </section>

      {actionError ? (
        <div className="flex items-start gap-2 rounded-md border border-destructive/40 bg-destructive/10 p-3 text-sm text-destructive">
          <AlertTriangle className="mt-0.5 h-4 w-4 flex-shrink-0" />
          <span>{actionError}</span>
        </div>
      ) : null}

      {conflictMessage ? (
        <div className="flex flex-wrap items-start justify-between gap-3 rounded-md border border-amber-400/35 bg-amber-400/10 p-3 text-sm text-amber-100">
          <div className="flex max-w-3xl items-start gap-2">
            <AlertTriangle className="mt-0.5 h-4 w-4 flex-shrink-0" />
            <span>{conflictMessage}</span>
          </div>
          <div className="flex gap-2">
            <button
              type="button"
              onClick={() => void refreshCurrentTable()}
              className="rounded border border-amber-300/40 px-2 py-1 text-xs font-medium hover:bg-amber-300/10"
            >
              Refresh page
            </button>
            <button
              type="button"
              onClick={() => void openFreshSession()}
              className="rounded border border-amber-300/40 px-2 py-1 text-xs font-medium hover:bg-amber-300/10"
            >
              Open fresh session
            </button>
          </div>
        </div>
      ) : null}

      {validation ? (
        <section
          className={`rounded-lg border p-4 ${
            validation.valid
              ? 'border-emerald-400/35 bg-emerald-400/10'
              : 'border-destructive/40 bg-destructive/10'
          }`}
        >
          <div className="flex items-center gap-2 text-sm font-semibold">
            {validation.valid ? (
              <CheckCircle2 className="h-4 w-4 text-emerald-300" />
            ) : (
              <AlertTriangle className="h-4 w-4 text-destructive" />
            )}
            {validation.valid
              ? 'Snapshot is ready to commit.'
              : `${validation.issues.length} validation issue${validation.issues.length === 1 ? '' : 's'} found.`}
          </div>
          {!validation.valid ? (
            <ul className="mt-3 space-y-1 text-xs text-muted-foreground">
              {validation.issues.slice(0, 8).map((issue) => (
                <li key={`${issue.entity_type}-${issue.row_id}-${issue.field}-${issue.message}`}>
                  <span className="font-medium text-foreground">
                    {issue.entity_type} · {issue.row_id}
                    {issue.field ? ` · ${issue.field}` : ''}
                  </span>
                  {' — '}
                  {issue.message}
                </li>
              ))}
              {validation.issues.length > 8 ? (
                <li>And {validation.issues.length - 8} more issue(s).</li>
              ) : null}
            </ul>
          ) : null}
        </section>
      ) : null}

      {previewBaseline.data ? (
        <section className="grid gap-3 rounded-lg border border-primary/35 bg-primary/5 p-4 sm:grid-cols-4">
          <div className="sm:col-span-2">
            <div className="text-sm font-semibold">Preview baseline</div>
            <p className="mt-1 text-xs text-muted-foreground">
              {previewBaseline.data.network.summary}
            </p>
          </div>
          <div>
            <div className="text-xs text-muted-foreground">Routes</div>
            <div className="mt-1 text-lg font-semibold">
              {previewBaseline.data.kpis.route_count}
            </div>
          </div>
          <div>
            <div className="text-xs text-muted-foreground">Total cost</div>
            <div className="mt-1 text-lg font-semibold">
              ${previewBaseline.data.kpis.cost_breakdown.total_cost.toLocaleString()}
            </div>
          </div>
        </section>
      ) : null}

      <section className="rounded-lg border border-border bg-card p-3">
        <div className="flex flex-wrap items-center justify-between gap-3">
          <div className="flex flex-wrap gap-1">
            {editorEntities.map((entity) => (
              <button
                key={entity}
                type="button"
                onClick={() => {
                  setEntityType(entity)
                  setPage(1)
                  setValidation(null)
                  setConflictMessage(null)
                }}
                className={`rounded-md px-3 py-2 text-xs font-medium transition-colors ${
                  entityType === entity
                    ? 'bg-primary/15 text-primary'
                    : 'text-muted-foreground hover:bg-accent hover:text-foreground'
                }`}
              >
                {dataEditorTables[entity].label}
                <span className="ml-1.5 text-[10px] opacity-80">
                  {session.entity_counts[entity]}
                </span>
              </button>
            ))}
          </div>
          {!isOpen ? (
            <button
              type="button"
              onClick={() => void openFreshSession()}
              disabled={busy}
              className="inline-flex items-center gap-2 rounded-md border border-border px-3 py-2 text-xs font-semibold hover:bg-accent disabled:cursor-not-allowed disabled:opacity-50"
            >
              <RefreshCw className="h-3.5 w-3.5" />
              Open new session
            </button>
          ) : null}
        </div>
      </section>

      {rows.isLoading ? (
        <div className="flex h-72 items-center justify-center rounded-lg border border-border bg-card text-sm text-muted-foreground">
          <Loader2 className="mr-2 h-4 w-4 animate-spin" />
          Loading {activeTable.label.toLowerCase()}...
        </div>
      ) : rows.error ? (
        <ErrorState title={`Could not load ${activeTable.label.toLowerCase()}`} error={rows.error} />
      ) : (
        <>
          <DataEditorTable
            entityType={entityType}
            rows={rows.data?.rows ?? []}
            disabled={!isOpen}
            busy={busy}
            onInsert={async (data) => {
              if (!sessionId) return
              await mutateAndRefresh(() =>
                insertRow.mutateAsync({
                  sessionId,
                  entityType,
                  payload: { data },
                }),
              )
            }}
            onPatch={async (rowId, rowVersion, changes) => {
              if (!sessionId) return
              await mutateAndRefresh(() =>
                patchRow.mutateAsync({
                  sessionId,
                  entityType,
                  rowId,
                  payload: { row_version: rowVersion, changes },
                }),
              )
            }}
            onDelete={async (rowId, rowVersion) => {
              if (!sessionId) return
              await mutateAndRefresh(async () => {
                const nextSession = await deleteRow.mutateAsync({
                  sessionId,
                  entityType,
                  rowId,
                  payload: { row_version: rowVersion },
                })
                setSession(nextSession)
              })
            }}
          />

          <div className="flex flex-wrap items-center justify-between gap-3 text-xs text-muted-foreground">
            <span>
              {total === 0
                ? 'No rows'
                : `${(page - 1) * pageSize + 1}–${Math.min(page * pageSize, total)} of ${total}`}
            </span>
            <div className="flex items-center gap-2">
              <button
                type="button"
                disabled={page <= 1 || busy}
                onClick={() => setPage((current) => current - 1)}
                className="rounded border border-border px-2 py-1 disabled:cursor-not-allowed disabled:opacity-50"
              >
                Previous
              </button>
              <span>Page {pageLabel}</span>
              <button
                type="button"
                disabled={page >= totalPages || busy}
                onClick={() => setPage((current) => current + 1)}
                className="rounded border border-border px-2 py-1 disabled:cursor-not-allowed disabled:opacity-50"
              >
                Next
              </button>
            </div>
          </div>
        </>
      )}

      <section className="flex flex-col gap-4 rounded-lg border border-border bg-card p-4 xl:flex-row xl:items-end xl:justify-between">
        <div className="grid gap-3 sm:grid-cols-2">
          <label className="flex min-w-48 flex-col gap-1 text-xs">
            <span className="font-medium">Preview depot</span>
            <select
              value={previewDepotId}
              disabled={!isOpen || busy}
              onChange={(event) => setPreviewDepotId(event.target.value)}
              className="rounded-md border border-border bg-background px-3 py-2 text-sm disabled:cursor-not-allowed disabled:opacity-50"
            >
              {(depots.data ?? []).map((depot) => (
                <option key={depot.depot_id} value={depot.depot_id}>
                  {depot.name}
                </option>
              ))}
            </select>
          </label>
          <label className="flex min-w-40 flex-col gap-1 text-xs">
            <span className="font-medium">Preview delivery day</span>
            <select
              value={previewDeliveryDay}
              disabled={!isOpen || busy}
              onChange={(event) => setPreviewDeliveryDay(event.target.value)}
              className="rounded-md border border-border bg-background px-3 py-2 text-sm disabled:cursor-not-allowed disabled:opacity-50"
            >
              {(days.data ?? []).map((day) => (
                <option key={day} value={day}>
                  {day}
                </option>
              ))}
            </select>
          </label>
        </div>
        <div className="flex flex-wrap gap-2">
          <button
            type="button"
            disabled={!isOpen || busy}
            onClick={() => void handleValidate()}
            className="inline-flex items-center gap-2 rounded-md border border-border px-3 py-2 text-xs font-semibold hover:bg-accent disabled:cursor-not-allowed disabled:opacity-50"
          >
            <CheckCircle2 className="h-3.5 w-3.5" />
            Validate
          </button>
          <button
            type="button"
            disabled={!isOpen || busy}
            onClick={() => void handlePreview()}
            className="inline-flex items-center gap-2 rounded-md border border-border px-3 py-2 text-xs font-semibold hover:bg-accent disabled:cursor-not-allowed disabled:opacity-50"
          >
            <Eye className="h-3.5 w-3.5" />
            Preview baseline
          </button>
          <button
            type="button"
            disabled={!isOpen || busy || !session.has_unsaved_changes}
            onClick={() => void handleDiscard()}
            className="inline-flex items-center gap-2 rounded-md border border-destructive/40 px-3 py-2 text-xs font-semibold text-destructive hover:bg-destructive/10 disabled:cursor-not-allowed disabled:opacity-50"
          >
            <Trash2 className="h-3.5 w-3.5" />
            Discard
          </button>
          <button
            type="button"
            disabled={!isOpen || busy || !session.has_unsaved_changes}
            onClick={() => void handleCommit()}
            className="inline-flex items-center gap-2 rounded-md bg-primary px-3 py-2 text-xs font-semibold text-primary-foreground disabled:cursor-not-allowed disabled:opacity-50"
          >
            {commitSession.isPending ? (
              <Loader2 className="h-3.5 w-3.5 animate-spin" />
            ) : (
              <Save className="h-3.5 w-3.5" />
            )}
            Commit baseline
          </button>
        </div>
      </section>
    </div>
  )
}
