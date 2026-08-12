import React from 'react'

export default class ErrorBoundary extends React.Component {
  constructor(props) {
    super(props)
    this.state = { error: null }
  }

  static getDerivedStateFromError(error) {
    return { error }
  }

  componentDidUpdate(prevProps) {
    if (this.state.error && prevProps.resetKey !== this.props.resetKey) {
      this.setState({ error: null })
    }
  }

  render() {
    if (!this.state.error) return this.props.children

    const message = this.state.error?.message || 'Something went wrong while loading this page.'
    return (
      <div className="flex min-h-[60vh] items-center justify-center bg-slate-50 p-6">
        <div className="w-full max-w-lg rounded-lg border border-slate-200 bg-white p-6 shadow-sm">
          <p className="text-xs font-bold uppercase tracking-wide text-red-500">Page Error</p>
          <h1 className="mt-2 text-xl font-bold text-slate-950">This screen could not load</h1>
          <p className="mt-2 text-sm leading-6 text-slate-600">{message}</p>
          <div className="mt-5 flex flex-wrap gap-2">
            <button
              type="button"
              onClick={() => this.setState({ error: null })}
              className="rounded-lg bg-blue-600 px-4 py-2 text-sm font-semibold text-white hover:bg-blue-700"
            >
              Try Again
            </button>
            <button
              type="button"
              onClick={() => window.location.assign('/dashboard')}
              className="rounded-lg border border-slate-200 px-4 py-2 text-sm font-semibold text-slate-700 hover:bg-slate-50"
            >
              Go To Dashboard
            </button>
            <button
              type="button"
              onClick={() => window.location.reload()}
              className="rounded-lg border border-slate-200 px-4 py-2 text-sm font-semibold text-slate-700 hover:bg-slate-50"
            >
              Reload App
            </button>
          </div>
        </div>
      </div>
    )
  }
}
