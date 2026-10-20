import { Component, type ErrorInfo, type ReactNode } from "react";

// Last line of defence: a rendering bug shows a recoverable message instead of a blank page.
export class ErrorBoundary extends Component<{ children: ReactNode }, { failed: boolean }> {
  state = { failed: false };

  static getDerivedStateFromError(): { failed: boolean } {
    return { failed: true };
  }

  componentDidCatch(error: Error, info: ErrorInfo): void {
    console.error("UI error", error, info.componentStack);
  }

  render(): ReactNode {
    if (this.state.failed) {
      return (
        <div className="welcome" role="alert">
          <h1>Something went wrong</h1>
          <p className="muted">Please reload the page. If the problem persists, contact support@cloudbox.example.</p>
          <button type="button" className="ghost" onClick={() => window.location.reload()}>
            Reload
          </button>
        </div>
      );
    }
    return this.props.children;
  }
}
