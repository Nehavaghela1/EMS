import { Component, type ErrorInfo, type ReactNode } from "react";

interface Props {
  children: ReactNode;
}

interface State {
  error: Error | null;
}

/** Catches render errors so a bug in one page shows a message instead of a
 * blank white screen (Spec 14.4). Real Sentry reporting is wired in a later
 * work package (16.3) — this logs to the console in the meantime, which is
 * still strictly better than swallowing the error silently. */
export class ErrorBoundary extends Component<Props, State> {
  state: State = { error: null };

  static getDerivedStateFromError(error: Error): State {
    return { error };
  }

  componentDidCatch(error: Error, info: ErrorInfo) {
    console.error("Unhandled render error", error, info.componentStack);
  }

  render() {
    if (this.state.error) {
      return (
        <div className="center-screen">
          <div className="card stack" style={{ maxWidth: 420 }}>
            <h2 style={{ margin: 0 }}>Something went wrong</h2>
            <p className="text-muted">
              This page hit an unexpected error. Reloading usually fixes it.
            </p>
            <button className="btn btn-primary" onClick={() => window.location.reload()}>
              Reload page
            </button>
          </div>
        </div>
      );
    }
    return this.props.children;
  }
}
