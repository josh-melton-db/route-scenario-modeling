import { AlertCircle } from 'lucide-react'

export default function ErrorState({
  title,
  error,
}: {
  title: string
  error: unknown
}) {
  return (
    <div className="flex h-full items-center justify-center p-8">
      <div className="flex max-w-xl items-start gap-2 rounded-md border border-destructive/40 bg-destructive/10 p-4 text-sm text-destructive">
        <AlertCircle className="mt-0.5 h-4 w-4 flex-shrink-0" />
        <div>
          <div className="font-medium">{title}</div>
          <div className="mt-1 text-xs break-all">{String(error)}</div>
        </div>
      </div>
    </div>
  )
}
