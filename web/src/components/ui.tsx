/**
 * Atomic pieces: no business logic, props only.
 *
 * Every async action has a visible loading state, every error appears near what
 * failed, and every list has a designed empty state — that is what these exist
 * to make cheap. They are drawn with the prototype's patterns (styles/app.css)
 * and the Organic design system's classes, so a screen composes them rather
 * than restyling anything.
 */

import {
  cloneElement,
  isValidElement,
  useId,
  type CSSProperties,
  type ReactElement,
  type ReactNode,
} from "react";

export function Button({
  children,
  onClick,
  variant = "primary",
  busy = false,
  disabled = false,
  block = false,
  type = "button",
}: {
  children: ReactNode;
  onClick?: () => void;
  variant?: "primary" | "secondary" | "ghost" | "danger";
  busy?: boolean;
  disabled?: boolean;
  block?: boolean;
  type?: "button" | "submit";
}) {
  const className = [
    "btn",
    variant === "danger" ? "btn-danger" : `btn-${variant}`,
    block ? "btn-block" : "",
  ]
    .filter(Boolean)
    .join(" ");
  return (
    <button
      type={type}
      className={className}
      onClick={onClick}
      disabled={disabled || busy}
      aria-busy={busy || undefined}
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
  const inputId = useId();
  const hintId = useId();

  // The hint is linked with aria-describedby and kept OUT of the <label>.
  // Inside the label it would become part of the field's accessible name, so a
  // screen reader would announce the whole sentence as the field's name
  // instead of "Password", and then read it again as help.
  const control = isValidElement(children)
    ? cloneElement(children as ReactElement<Record<string, unknown>>, {
        id: inputId,
        ...(hint ? { "aria-describedby": hintId } : {}),
      })
    : children;

  return (
    <div style={{ marginBottom: 14 }}>
      <label htmlFor={inputId} className="field-label">
        {label}
      </label>
      {control}
      {hint && (
        <span
          id={hintId}
          className="muted"
          style={{ display: "block", fontSize: 12.5, marginTop: 5 }}
        >
          {hint}
        </span>
      )}
    </div>
  );
}

export function ErrorNote({ error }: { error: string | null }) {
  if (!error) return null;
  return (
    <p
      role="alert"
      style={{
        color: "var(--status-critical)",
        fontSize: 13.5,
        fontWeight: 600,
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

/** A confirmation that something worked. */
export function Done({ children }: { children: ReactNode }) {
  return (
    <p role="status" className="note-good" style={{ margin: "8px 0" }}>
      <span aria-hidden="true">✓</span> {children}
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
    <div
      className="panel"
      style={{ textAlign: "center", padding: "32px 24px" }}
    >
      <p className="card-title" style={{ margin: 0 }}>
        {title}
      </p>
      {children && (
        <p className="subcopy" style={{ marginTop: 6, marginBottom: 0 }}>
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

/** A labelled number on the page ground: the prototype's stat inset. */
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
    <div className="inset" style={{ padding: "12px 14px" }}>
      <div className="stat-label">{label}</div>
      <div className="stat-value">{value}</div>
      {note && (
        <div className="subcopy" style={{ fontSize: 12 }}>
          {note}
        </div>
      )}
    </div>
  );
}

/**
 * The prototype's responsive grid: repeat(auto-fit, minmax(col, 1fr)). A
 * column never forces a horizontal scroll on a phone (see .auto-grid).
 */
export function AutoGrid({
  col,
  gap = 24,
  children,
  style,
}: {
  col: number;
  gap?: number;
  children: ReactNode;
  style?: CSSProperties;
}) {
  const vars = { "--col": `${col}px`, "--gap": `${gap}px` } as CSSProperties;
  return (
    <div className="auto-grid" style={{ ...vars, ...style }}>
      {children}
    </div>
  );
}

/** The prototype's surface card. */
export function Panel({
  children,
  tight = false,
  column = false,
  style,
  label,
}: {
  children: ReactNode;
  tight?: boolean;
  column?: boolean;
  style?: CSSProperties;
  label?: string;
}) {
  const className = [
    "panel",
    tight ? "panel-tight" : "",
    column ? "panel-column" : "",
  ]
    .filter(Boolean)
    .join(" ");
  return (
    <section className={className} style={style} aria-label={label}>
      {children}
    </section>
  );
}

export function Eyebrow({
  children,
  style,
}: {
  children: ReactNode;
  style?: CSSProperties;
}) {
  return (
    <div className="eyebrow" style={style}>
      {children}
    </div>
  );
}

/** One option of a pill group; pressed when it is the current choice. */
export function PillToggle({
  pressed,
  onClick,
  children,
  small = false,
  disabled = false,
}: {
  pressed: boolean;
  onClick: () => void;
  children: ReactNode;
  small?: boolean;
  disabled?: boolean;
}) {
  return (
    <button
      type="button"
      className={small ? "pill-toggle pill-toggle-sm" : "pill-toggle"}
      aria-pressed={pressed}
      disabled={disabled}
      onClick={onClick}
    >
      {children}
    </button>
  );
}

/** The prototype's round checkbox, with its label beside it. */
export function RoundCheck({
  checked,
  onChange,
  children,
  disabled = false,
}: {
  checked: boolean;
  onChange: (checked: boolean) => void;
  children: ReactNode;
  disabled?: boolean;
}) {
  return (
    <button
      type="button"
      role="checkbox"
      aria-checked={checked}
      aria-disabled={disabled || undefined}
      className="round-check"
      onClick={() => {
        if (!disabled) onChange(!checked);
      }}
    >
      <span className="round-check-box" aria-hidden="true" />
      <span style={{ flex: 1 }}>{children}</span>
    </button>
  );
}

/** A score against a bar, both on 0–100: the fill is you, the mark is the bar. */
export function YouVsBar({
  you,
  bar,
  label,
}: {
  you: number;
  bar: number;
  label: string;
}) {
  const clamp = (value: number) => Math.max(0, Math.min(100, value));
  return (
    <div
      className="you-vs-bar"
      role="img"
      aria-label={`${label}: you ${you}, the bar is ${bar}`}
    >
      <div className="you-vs-bar-fill" style={{ width: `${clamp(you)}%` }} />
      <div className="you-vs-bar-mark" style={{ left: `${clamp(bar)}%` }} />
    </div>
  );
}

export function ProgressBar({
  percent,
  label,
}: {
  percent: number;
  label: string;
}) {
  const value = Math.max(0, Math.min(100, Math.round(percent)));
  return (
    <div
      className="progress"
      role="progressbar"
      aria-label={label}
      aria-valuemin={0}
      aria-valuemax={100}
      aria-valuenow={value}
    >
      <div className="progress-fill" style={{ width: `${value}%` }} />
    </div>
  );
}

/** Fit as a badge; the prototype's bands are 85+ and 70+. */
export function FitBadge({ fit }: { fit: number | null }) {
  const band =
    fit === null ? undefined : fit >= 85 ? "high" : fit >= 70 ? "mid" : "low";
  return (
    <span className="fit-badge" data-band={band}>
      {fit === null ? "—" : `${fit}%`}
    </span>
  );
}

export type Verdict = "covered" | "partial" | "gap";

const VERDICT_LABELS: Record<Verdict, string> = {
  covered: "Covered",
  partial: "Partial",
  gap: "Gap",
};

export function VerdictBadge({ verdict }: { verdict: Verdict }) {
  return (
    <span className="verdict-badge" data-verdict={verdict}>
      {VERDICT_LABELS[verdict]}
    </span>
  );
}
