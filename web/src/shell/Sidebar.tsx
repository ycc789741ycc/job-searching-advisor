import { JOURNEY, MODEL_SCREEN, type Screen } from "./navigation";
import type { ShellStatus } from "./ShellContext";

/** The prototype's left rail: the numbered journey, the model, confidence. */
export function Sidebar({
  current,
  status,
  onNavigate,
}: {
  current: Screen;
  status: ShellStatus;
  onNavigate: (screen: Screen) => void;
}) {
  const noKey = !status.credential;
  const keyFailed = status.credential?.status === "failed";

  return (
    <aside className="sidebar">
      <div className="brand">
        <span className="brand-dot" aria-hidden="true" />
        Job Searching Advisor
      </div>

      <nav aria-label="Screens">
        <ul className="nav-list">
          {JOURNEY.map((item) => {
            const flag =
              item.id === "questions" && status.openQuestions > 0
                ? String(status.openQuestions)
                : null;
            return (
              <li key={item.id}>
                <button
                  type="button"
                  className="nav-item"
                  aria-current={current === item.id ? "page" : undefined}
                  onClick={() => onNavigate(item.id)}
                >
                  <span className="nav-num" aria-hidden="true">
                    {item.num}
                  </span>
                  {item.label}
                  {flag && (
                    <span
                      className="nav-flag"
                      aria-label={`${flag} unanswered`}
                    >
                      {flag}
                    </span>
                  )}
                </button>
              </li>
            );
          })}
        </ul>

        <div className="sidebar-section">
          <div className="eyebrow">System configuration</div>
          <button
            type="button"
            className="nav-item"
            style={{ padding: "8px 10px" }}
            aria-current={current === MODEL_SCREEN.id ? "page" : undefined}
            onClick={() => onNavigate(MODEL_SCREEN.id)}
          >
            <span className="nav-ring" aria-hidden="true" />
            <span style={{ minWidth: 0 }}>
              {MODEL_SCREEN.label}
              <span className="nav-note">
                {status.credential
                  ? `${status.credential.model}${keyFailed ? " · key failed" : ""}`
                  : "No key yet"}
              </span>
            </span>
            {(noKey || keyFailed) && (
              <span
                className="nav-flag"
                aria-label={noKey ? "needs a key" : "key failed"}
              >
                !
              </span>
            )}
          </button>
        </div>
      </nav>

      <div className="confidence">
        <div className="eyebrow">Profile confidence</div>
        {status.confidence === null ? (
          <p className="confidence-note" style={{ marginTop: 8 }}>
            Run the analysis to see how sure it is.
          </p>
        ) : (
          <>
            <div
              className="progress"
              style={{ height: 10, marginTop: 10 }}
              role="progressbar"
              aria-label="Profile confidence"
              aria-valuemin={0}
              aria-valuemax={100}
              aria-valuenow={status.confidence}
            >
              <div
                className="progress-fill"
                style={{ width: `${status.confidence}%` }}
              />
            </div>
            <div className="confidence-value">{status.confidence}%</div>
            <p className="confidence-note">
              {status.confidence > 85
                ? "Enough to trust the salary bands."
                : status.openQuestions > 0
                  ? "Answer the open questions to tighten the report."
                  : "Connect another source to tighten the report."}
            </p>
          </>
        )}
      </div>
    </aside>
  );
}
