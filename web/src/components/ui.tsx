/**
 * Atomic pieces: no business logic, props only.
 *
 * Every async action has a visible loading state, every error appears near what
 * failed, and every list has a designed empty state — that is what these exist
 * to make cheap.
 */

import type { ReactNode } from "react";

export function Button({
  children,
  onClick,
  variant = "primary",
  busy = false,
  disabled = false,
  type = "button",
}: {
  children: ReactNode;
  onClick?: () => void;
  variant?: "primary" | "secondary" | "danger";
  busy?: boolean;
  disabled?: boolean;
  type?: "button" | "submit";
}) {
  const palette = {
    primary: { bg: "var(--series-1)", fg: "#ffffff", border: "transparent" },
    secondary: {
      bg: "transparent",
      fg: "var(--text-primary)",
      border: "var(--border)",
    },
    danger: {
      bg: "transparent",
      fg: "var(--status-critical)",
      border: "var(--border)",
    },
  }[variant];

  return (
    <button
      type={type}
      onClick={onClick}
      disabled={disabled || busy}
      style={{
        background: palette.bg,
        color: palette.fg,
        border: `1px solid ${palette.border}`,
        borderRadius: 8,
        padding: "8px 14px",
        font: "inherit",
        fontWeight: 600,
        fontSize: 14,
        cursor: disabled || busy ? "not-allowed" : "pointer",
        opacity: disabled || busy ? 0.6 : 1,
      }}
    >
      {busy ? "Working…" : children}
    </button>
  );
}

export function Field({
  label,
  hint,
  children,
}: {
  label: string;
  hint?: string;
  children: ReactNode;
}) {
  return (
    <label style={{ display: "block", marginBottom: 14 }}>
      <span
        style={{
          display: "block",
          fontWeight: 600,
          fontSize: 13.5,
          marginBottom: 4,
        }}
      >
        {label}
      </span>
      {children}
      {hint && (
        <span
          className="muted"
          style={{ display: "block", fontSize: 12.5, marginTop: 4 }}
        >
          {hint}
        </span>
      )}
    </label>
  );
}

export const inputStyle = {
  width: "100%",
  padding: "8px 10px",
  borderRadius: 8,
  border: "1px solid var(--border)",
  background: "var(--surface-1)",
  color: "var(--text-primary)",
  font: "inherit",
  fontSize: 14,
} as const;

export function ErrorNote({ error }: { error: string | null }) {
  if (!error) return null;
  return (
    <p
      role="alert"
      style={{
        color: "var(--status-critical)",
        fontSize: 13.5,
        margin: "8px 0",
        display: "flex",
        gap: 6,
      }}
    >
      {/* Never colour alone. */}
      <span aria-hidden="true">⚠</span>
      {error}
    </p>
  );
}

export function EmptyState({
  title,
  children,
}: {
  title: string;
  children?: ReactNode;
}) {
  return (
    <div style={{ padding: "24px 0", textAlign: "center" }}>
      <p style={{ fontWeight: 600, margin: 0 }}>{title}</p>
      {children && (
        <p className="muted" style={{ fontSize: 13.5, marginTop: 6 }}>
          {children}
        </p>
      )}
    </div>
  );
}

export function Loading({ what }: { what: string }) {
  return (
    <p className="muted" role="status" style={{ fontSize: 13.5 }}>
      Loading {what}…
    </p>
  );
}

export function StatTile({
  label,
  value,
  note,
}: {
  label: string;
  value: string;
  note?: string;
}) {
  return (
    <div className="card" style={{ minWidth: 150 }}>
      <div className="muted" style={{ fontSize: 12.5 }}>
        {label}
      </div>
      <div
        style={{ fontSize: 28, fontWeight: 700, lineHeight: 1.1, marginTop: 2 }}
      >
        {value}
      </div>
      {note && (
        <div className="muted" style={{ fontSize: 12.5, marginTop: 2 }}>
          {note}
        </div>
      )}
    </div>
  );
}
