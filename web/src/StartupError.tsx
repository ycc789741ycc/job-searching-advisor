import { Component, type ErrorInfo, type ReactNode } from "react";

/**
 * What the page shows when the app cannot start.
 *
 * A misconfigured deployment used to render nothing at all, which gives whoever
 * is setting it up no idea what to fix. Configuration is supplied at run time,
 * so getting it wrong is an ordinary situation and deserves an ordinary,
 * actionable message.
 */
export function StartupError({ error }: { error: unknown }) {
  const message = error instanceof Error ? error.message : String(error);

  return (
    <div
      role="alert"
      style={{
        maxWidth: 640,
        margin: "12vh auto",
        padding: "0 20px",
        fontFamily: "system-ui, -apple-system, 'Segoe UI', sans-serif",
        color: "var(--text-primary, #0b0b0b)",
      }}
    >
      <h1 style={{ fontSize: 22, marginBottom: 8 }}>The app could not start</h1>
      <p style={{ color: "var(--text-secondary, #52514e)", fontSize: 15 }}>
        This is a configuration problem, not a bug in the page. The details:
      </p>
      <pre
        style={{
          background: "var(--surface-1, #fcfcfb)",
          border: "1px solid var(--border, rgba(11,11,11,0.1))",
          borderRadius: 8,
          padding: "12px 14px",
          fontSize: 13,
          whiteSpace: "pre-wrap",
          overflowWrap: "anywhere",
        }}
      >
        {message}
      </pre>
      <p style={{ color: "var(--text-secondary, #52514e)", fontSize: 14 }}>
        The SPA reads its settings from <code>/config.js</code>, which its
        container writes from the environment at start. Fix the values in{" "}
        <code>.env</code>, then run{" "}
        <code>make stop-app &amp;&amp; make start-app</code>.
      </p>
    </div>
  );
}

interface Props {
  children: ReactNode;
}

interface State {
  error: unknown;
}

/** Catches anything thrown while the tree first renders. */
export class StartupBoundary extends Component<Props, State> {
  state: State = { error: null };

  static getDerivedStateFromError(error: unknown): State {
    return { error };
  }

  componentDidCatch(error: unknown, info: ErrorInfo): void {
    // Keep the stack in the console for whoever is debugging the container.
    console.error("The app failed to start", error, info.componentStack);
  }

  render(): ReactNode {
    if (this.state.error) return <StartupError error={this.state.error} />;
    return this.props.children;
  }
}
