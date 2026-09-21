export default function EmptyState({
  title,
  description,
  action,
}: {
  title: string
  description: string
  action?: { label: string; onClick: () => void }
}) {
  return (
    <div className="flex h-full items-center justify-center p-8 text-center">
      <div className="max-w-md rounded-lg border border-border bg-card p-6">
        <div className="text-base font-semibold">{title}</div>
        <p className="mt-2 text-sm text-muted-foreground">{description}</p>
        {action && (
          <button
            type="button"
            onClick={action.onClick}
            className="mt-4 inline-flex h-9 items-center rounded-md bg-primary px-4 text-sm font-semibold text-primary-foreground"
          >
            {action.label}
          </button>
        )}
      </div>
    </div>
  )
}
