import { Component, type ErrorInfo, type ReactNode } from 'react'

interface Props { children: ReactNode }
interface State { error: Error | null }

export class AppErrorBoundary extends Component<Props, State> {
  state: State = { error: null }

  static getDerivedStateFromError(error: Error): State {
    return { error }
  }

  componentDidCatch(error: Error, info: ErrorInfo) {
    console.error('Application render failure', error, info.componentStack)
  }

  render() {
    if (!this.state.error) return this.props.children
    return (
      <main className="mx-auto flex min-h-screen max-w-xl flex-col justify-center gap-4 p-8">
        <h1 className="text-xl font-semibold">This page could not be displayed</h1>
        <p className="text-sm text-muted-foreground">
          Reload the page. If the problem continues, share the request time with your administrator.
        </p>
        <button className="w-fit rounded-md bg-primary px-4 py-2 text-primary-foreground" onClick={() => window.location.reload()}>
          Reload
        </button>
      </main>
    )
  }
}
