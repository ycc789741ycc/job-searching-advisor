import { useRef, useState } from "react";
import type { CallbackOutcome } from "./oauthCallback";
import { api } from "../api/client";
import type { Connection, Evidence, ResumeFile } from "../api/types";
import {
  AutoGrid,
  Button,
  Done,
  ErrorNote,
  Eyebrow,
  Loading,
} from "../components/ui";
import { useShell } from "../shell/ShellContext";
import { messageOf, useAsync } from "./useAsync";

const LABELS: Record<string, { name: string; kind: string; note: string }> = {
  github: {
    name: "GitHub",
    kind: "Code, reviews, RFCs",
    note: "Commits, reviews and RFCs — the work a resume usually flattens.",
  },
  jira: {
    name: "Jira",
    kind: "Delivery scope",
    note: "Cycle time, epic ownership and incident response — your scope.",
  },
};

/** Where evidence comes from: authorised sources and an uploaded resume. */
export function Connect({ callback }: { callback?: CallbackOutcome | null }) {
  const { navigate } = useShell();
  // Refetched when a callback finishes, so a fresh connection shows as
  // connected without a reload.
  const connections = useAsync<Connection[]>(
    () => api.get("/connections"),
    [callback],
  );
  const resumes = useAsync<ResumeFile[]>(() => api.get("/resumes"), []);
  const evidence = useAsync<Evidence[]>(() => api.get("/evidence"), []);
  const fileInput = useRef<HTMLInputElement>(null);
  const [busy, setBusy] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);

  async function connect(kind: string) {
    setBusy(kind);
    setError(null);
    try {
      const { url } = await api.get<{ url: string }>(
        `/connections/${kind}/authorize-url`,
      );
      window.location.href = url;
    } catch (caught) {
      setError(messageOf(caught));
      setBusy(null);
    }
  }

  async function sync(kind: string) {
    setBusy(kind);
    setError(null);
    try {
      await api.post(`/connections/${kind}/sync`);
      await connections.reload();
    } catch (caught) {
      setError(messageOf(caught));
    } finally {
      setBusy(null);
    }
  }

  async function upload(file: File) {
    setBusy("resume");
    setError(null);
    try {
      await api.upload("/resumes", file);
      await resumes.reload();
    } catch (caught) {
      setError(messageOf(caught));
    } finally {
      setBusy(null);
    }
  }

  const facts = evidence.data ?? [];
  const bySource = countBy(facts, (item) => item.source);
  const latestResume = (resumes.data ?? [])[0];

  return (
    <AutoGrid col={340}>
      <div>
        <p className="lead" style={{ marginTop: 0 }}>
          Every connector runs on OAuth — you approve the scopes, we never hold
          a password, and every claim the analysis makes points back at
          something here.
        </p>
        {callback?.connected && <Done>{callback.message}</Done>}
        <ErrorNote
          error={callback && !callback.connected ? callback.message : error}
        />

        {connections.loading ? (
          <Loading what="your sources" />
        ) : (
          <div className="stack" style={{ marginTop: 18 }}>
            {(connections.data ?? []).map((connection) => {
              const label = LABELS[connection.kind] ?? {
                name: connection.kind,
                kind: "",
                note: "",
              };
              return (
                <div key={connection.kind} className="panel panel-tight">
                  <div
                    className="row-between"
                    style={{ alignItems: "flex-start" }}
                  >
                    <div
                      className="row"
                      style={{ gap: 14, flexWrap: "nowrap" }}
                    >
                      <SourceGlyph
                        name={label.name}
                        on={connection.connected}
                      />
                      <div>
                        <div className="card-title">{label.name}</div>
                        <div className="subcopy">{label.kind}</div>
                      </div>
                    </div>
                    <span
                      className={
                        connection.connected
                          ? "tag tag-accent-2"
                          : "tag tag-outline"
                      }
                    >
                      {connection.connected ? "Connected" : "Not connected"}
                    </span>
                  </div>
                  <p
                    className="subcopy"
                    style={{
                      fontSize: 13.5,
                      lineHeight: 1.55,
                      margin: "13px 0",
                    }}
                  >
                    {label.note}
                  </p>
                  {connection.last_error && (
                    <p
                      style={{
                        color: "var(--status-critical)",
                        fontSize: 13,
                        fontWeight: 600,
                      }}
                    >
                      <span aria-hidden="true">⚠</span> {connection.last_error}
                    </p>
                  )}
                  {!connection.connected && connection.scopes.length > 0 && (
                    <ul
                      className="subcopy"
                      style={{
                        fontSize: 12.5,
                        margin: "0 0 13px 18px",
                        padding: 0,
                      }}
                    >
                      {connection.scopes.map((scope) => (
                        <li key={scope}>{scope}</li>
                      ))}
                    </ul>
                  )}
                  <div className="row">
                    <Button
                      variant={connection.connected ? "secondary" : "primary"}
                      busy={busy === connection.kind}
                      onClick={() =>
                        connection.connected
                          ? sync(connection.kind)
                          : connect(connection.kind)
                      }
                    >
                      {connection.connected ? "Sync now" : "Connect"}
                    </Button>
                    {connection.connected && (
                      <span className="muted" style={{ fontSize: 12.5 }}>
                        {connection.account ? `${connection.account} · ` : ""}
                        {connection.last_synced_at
                          ? `last synced ${new Date(connection.last_synced_at).toLocaleDateString()}`
                          : "not synced yet"}
                      </span>
                    )}
                  </div>
                </div>
              );
            })}

            <div
              className="panel panel-tight row-between"
              style={{ alignItems: "center", flexWrap: "wrap" }}
            >
              <div>
                <div className="card-title">Existing résumé</div>
                <div className="subcopy" style={{ marginTop: 3 }}>
                  {latestResume
                    ? `${latestResume.filename} — ${latestResume.parse_error ?? latestResume.status}`
                    : "PDF or Word. Used as evidence now, and as the base document to revise later."}
                </div>
              </div>
              <input
                ref={fileInput}
                type="file"
                accept=".pdf,.docx,.txt"
                aria-label="Résumé file"
                style={{ display: "none" }}
                onChange={(event) => {
                  const file = event.target.files?.[0];
                  if (file) void upload(file);
                  event.target.value = "";
                }}
              />
              <div className="row">
                <Button
                  variant="secondary"
                  busy={busy === "resume"}
                  onClick={() => fileInput.current?.click()}
                >
                  Upload PDF / DOCX
                </Button>
                <Button onClick={() => navigate("strengths")}>
                  Analyze with AI
                </Button>
              </div>
            </div>
          </div>
        )}
      </div>

      <div className="stack" style={{ gap: 20 }}>
        <div className="callout">
          <Eyebrow style={{ marginBottom: 6 }}>What it found so far</Eyebrow>
          {evidence.loading ? (
            <Loading what="evidence" />
          ) : facts.length === 0 ? (
            <p
              className="callout-note"
              style={{ fontSize: 13.5, margin: "8px 0 0" }}
            >
              Nothing gathered yet. Connect a source or upload a résumé, then
              sync.
            </p>
          ) : (
            <>
              <div className="divided">
                {Object.entries(bySource).map(([source, count]) => (
                  <div
                    key={source}
                    style={{ display: "flex", gap: 14, alignItems: "baseline" }}
                  >
                    <div
                      className="stat-value"
                      style={{ fontSize: 22, minWidth: 58 }}
                    >
                      {count}
                    </div>
                    <div>
                      <div style={{ fontSize: 14, fontWeight: 600 }}>
                        {count === 1 ? "fact" : "facts"}
                      </div>
                      <div className="subcopy" style={{ fontSize: 12.5 }}>
                        from {sourceName(source)}
                      </div>
                    </div>
                  </div>
                ))}
              </div>
              <p
                className="callout-note"
                style={{ fontSize: 13.5, lineHeight: 1.55, margin: "14px 0 0" }}
              >
                {facts.length} facts, each traceable to where it came from.
              </p>
            </>
          )}
        </div>

        {facts.length > 0 && (
          <div className="panel">
            <h3>Evidence gathered</h3>
            <p className="subcopy">The first 50, grouped by source.</p>
            <div className="table-scroll">
              <table className="data-table">
                <thead>
                  <tr>
                    <th>Source</th>
                    <th>Fact</th>
                  </tr>
                </thead>
                <tbody>
                  {facts.slice(0, 50).map((item) => (
                    <tr key={item.id}>
                      <td className="muted" style={{ minWidth: 120 }}>
                        {item.reference}
                      </td>
                      <td>{item.fact}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </div>
        )}
      </div>
    </AutoGrid>
  );
}

function SourceGlyph({ name, on }: { name: string; on: boolean }) {
  return (
    <div
      aria-hidden="true"
      style={{
        width: 42,
        height: 42,
        flex: "0 0 auto",
        borderRadius: 999,
        background: on
          ? "var(--color-accent-2-200)"
          : "var(--color-accent-200)",
        color: on ? "var(--color-accent-2-800)" : "var(--color-accent-800)",
        display: "flex",
        alignItems: "center",
        justifyContent: "center",
        fontFamily: "var(--font-heading)",
        fontSize: 15,
      }}
    >
      {name.slice(0, 2)}
    </div>
  );
}

const SOURCE_NAMES: Record<string, string> = {
  resume: "your résumé",
  self_reported: "your answers",
};

function sourceName(source: string): string {
  return LABELS[source]?.name ?? SOURCE_NAMES[source] ?? source;
}

function countBy<T>(
  items: T[],
  key: (item: T) => string,
): Record<string, number> {
  const counts: Record<string, number> = {};
  for (const item of items) counts[key(item)] = (counts[key(item)] ?? 0) + 1;
  return counts;
}
