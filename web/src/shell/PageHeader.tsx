import { useState } from "react";
import type { ScreenMeta } from "./navigation";
import type { ShellStatus } from "./ShellContext";

/** Kicker and title on the left; model, target and account on the right. */
export function PageHeader({
  meta,
  status,
  target,
  email,
  onSignOut,
}: {
  meta: ScreenMeta;
  status: ShellStatus;
  target: string | null;
  email: string | null;
  onSignOut: () => void;
}) {
  const [menuOpen, setMenuOpen] = useState(false);
  const model = status.credential?.model;

  return (
    <header className="page-header">
      <div>
        <div className="kicker">{meta.kicker}</div>
        <h1>{meta.title}</h1>
      </div>
      <div className="header-chips">
        <span className={model ? "chip" : "chip chip-warn"}>
          <span className="chip-dot" aria-hidden="true" />
          {model ?? "No model configured"}
        </span>
        {target && (
          <span className="chip" title={target}>
            {target}
          </span>
        )}
        <span style={{ position: "relative" }}>
          <button
            type="button"
            className="avatar"
            aria-haspopup="true"
            aria-expanded={menuOpen}
            aria-label={`Account${email ? ` ${email}` : ""}`}
            onClick={() => setMenuOpen((open) => !open)}
          >
            {initialsOf(email)}
          </button>
          {menuOpen && (
            <div
              className="panel"
              style={{
                position: "absolute",
                right: 0,
                top: 46,
                padding: 16,
                minWidth: 220,
                boxShadow: "var(--shadow-md)",
                zIndex: 20,
              }}
            >
              <p className="subcopy" style={{ margin: "0 0 10px" }}>
                Signed in as {email ?? "you"}
              </p>
              <button
                type="button"
                className="btn btn-secondary"
                onClick={onSignOut}
              >
                Sign out
              </button>
            </div>
          )}
        </span>
      </div>
    </header>
  );
}

/** Two letters from the address's local part: "maya.chen@…" → "MC". Pure. */
export function initialsOf(email: string | null): string {
  const local = (email ?? "").split("@")[0] ?? "";
  const parts = local.split(/[._\-+]+/).filter(Boolean);
  const letters =
    parts.length >= 2
      ? `${parts[0]![0]}${parts[1]![0]}`
      : local.slice(0, 2) || "?";
  return letters.toUpperCase();
}
