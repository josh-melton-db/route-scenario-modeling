export default function EmptyState({
  title,
  description,
}: {
  title: string
  description: string
}) {
  return (
    <div className="flex h-full items-center justify-center p-8 text-center">
      <div className="max-w-md rounded-lg border border-border bg-card p-6">
        <div className="text-base font-semibold">{title}</div>
        <p className="mt-2 text-sm text-muted-foreground">{description}</p>
      </div>
    </div>
  )
}
