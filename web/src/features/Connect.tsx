import { useRef, useState } from "react";
import { api } from "../api/client";
import type { Connection, Evidence, ResumeFile } from "../api/types";
import { Button, EmptyState, ErrorNote, Loading } from "../components/ui";
import { messageOf, useAsync } from "./useAsync";

const LABELS: Record<string, { name: string; note: string }> = {
  github: {
    name: "GitHub",
    note: "Commits, reviews and RFCs — the work a resume usually flattens.",
  },
  jira: {
    name: "Jira",
    note: "Cycle time, epic ownership and incident response — your scope.",
  },
};

/** Where evidence comes from: authorised sources and an uploaded resume. */
export function Connect() {
  const connections = useAsync<Connection[]>(() => api.get("/connections"), []);
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

  return (
    <section>
      <h1>Connect your work</h1>
      <p className="secondary" style={{ maxWidth: 620 }}>
        Everything the analysis says will point back at something here, so it
        can be checked rather than taken on trust.
      </p>
      <ErrorNote error={error} />

      {connections.loading ? (
        <Loading what="your sources" />
      ) : (
        <div style={{ display: "grid", gap: 12, marginTop: 16, maxWidth: 620 }}>
          {(connections.data ?? []).map((connection) => {
            const label = LABELS[connection.kind] ?? {
              name: connection.kind,
              note: "",
            };
            return (
              <div key={connection.kind} className="card">
                <div
                  style={{
                    display: "flex",
                    justifyContent: "space-between",
                    gap: 12,
                    alignItems: "flex-start",
                  }}
                >
                  <div>
                    <h3 style={{ margin: 0 }}>{label.name}</h3>
                    <p
                      className="muted"
                      style={{ fontSize: 13.5, margin: "4px 0 0" }}
                    >
                      {label.note}
                    </p>
                    {connection.connected && (
                      <p
                        className="secondary"
                        style={{ fontSize: 13, margin: "6px 0 0" }}
                      >
                        <span aria-hidden="true">✓</span> Connected
                        {connection.account ? ` as ${connection.account}` : ""}
                        {connection.last_synced_at
                          ? ` · last synced ${new Date(connection.last_synced_at).toLocaleDateString()}`
                          : " · not synced yet"}
                      </p>
                    )}
                    {connection.last_error && (
                      <p
                        style={{
                          color: "var(--status-critical)",
                          fontSize: 13,
                        }}
                      >
                        <span aria-hidden="true">⚠</span>{" "}
                        {connection.last_error}
                      </p>
                    )}
                  </div>
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
                </div>
                {!connection.connected && connection.scopes.length > 0 && (
                  <ul
                    className="muted"
                    style={{ fontSize: 12.5, margin: "10px 0 0 18px" }}
                  >
                    {connection.scopes.map((scope) => (
                      <li key={scope}>{scope}</li>
                    ))}
                  </ul>
                )}
              </div>
            );
          })}

          <div className="card">
            <h3 style={{ margin: 0 }}>Resume</h3>
            <p
              className="muted"
              style={{ fontSize: 13.5, margin: "4px 0 10px" }}
            >
              PDF or Word. Used as evidence now, and as the base document to
              revise later.
            </p>
            <input
              ref={fileInput}
              type="file"
              accept=".pdf,.docx,.txt"
              style={{ display: "none" }}
              onChange={(event) => {
                const file = event.target.files?.[0];
                if (file) void upload(file);
                event.target.value = "";
              }}
            />
            <Button
              variant="secondary"
              busy={busy === "resume"}
              onClick={() => fileInput.current?.click()}
            >
              Upload a resume
            </Button>
            <ul style={{ fontSize: 13.5, margin: "10px 0 0 18px" }}>
              {(resumes.data ?? []).map((resume) => (
                <li key={resume.id}>
                  {resume.filename} —{" "}
                  <span className={resume.parse_error ? "" : "muted"}>
                    {resume.parse_error ?? resume.status}
                  </span>
                </li>
              ))}
            </ul>
          </div>
        </div>
      )}

      <h2 style={{ marginTop: 28 }}>Evidence gathered</h2>
      {evidence.loading ? (
        <Loading what="evidence" />
      ) : (evidence.data ?? []).length === 0 ? (
        <EmptyState title="Nothing gathered yet">
          Connect a source or upload a resume, then sync.
        </EmptyState>
      ) : (
        <>
          <p className="secondary" style={{ fontSize: 13.5 }}>
            {evidence.data?.length} facts, each traceable to where it came from.
          </p>
          <table className="data-table" style={{ maxWidth: 820 }}>
            <thead>
              <tr>
                <th>Source</th>
                <th>Fact</th>
              </tr>
            </thead>
            <tbody>
              {(evidence.data ?? []).slice(0, 50).map((item) => (
                <tr key={item.id}>
                  <td className="muted" style={{ whiteSpace: "nowrap" }}>
                    {item.reference}
                  </td>
                  <td>{item.fact}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </>
      )}
    </section>
  );
}
