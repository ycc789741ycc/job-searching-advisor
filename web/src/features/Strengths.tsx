import { useState } from "react";
import { api } from "../api/client";
import type { Assessment, CostEstimate, Evidence } from "../api/types";
import { SkillRadar } from "../charts/SkillRadar";
import { Button, EmptyState, ErrorNote, Loading } from "../components/ui";
import { messageOf, useAsync } from "./useAsync";

/**
 * The strength report.
 *
 * Nothing is spent without asking: the first run shows its estimated cost and
 * waits for a yes.
 */
export function Strengths() {
  const assessment = useAsync<Assessment | null>(() => api.get("/assessments/latest"), []);
  const evidence = useAsync<Evidence[]>(() => api.get("/evidence"), []);
  const [estimate, setEstimate] = useState<CostEstimate | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [queued, setQueued] = useState(false);
  const [selected, setSelected] = useState<string | undefined>(undefined);

  async function askForEstimate() {
    setBusy(true);
    setError(null);
    try {
      setEstimate(await api.get<CostEstimate>("/assessments/cost-estimate"));
    } catch (caught) {
      setError(messageOf(caught));
    } finally {
      setBusy(false);
    }
  }

  async function confirm() {
    setBusy(true);
    setError(null);
    try {
      await api.post("/assessments");
      setQueued(true);
      setEstimate(null);
    } catch (caught) {
      setError(messageOf(caught));
    } finally {
      setBusy(false);
    }
  }

  const dimensions = (assessment.data?.dimensions ?? []).map((d) => ({
    key: d.key,
    name: d.name,
    shortName: d.short_name,
    score: d.score,
    confidence: d.confidence,
    read: d.read,
  }));
  const active = assessment.data?.dimensions.find((d) => d.key === selected);
  const byId = new Map((evidence.data ?? []).map((item) => [item.id, item]));

  return (
    <section>
      <div
        style={{
          display: "flex",
          justifyContent: "space-between",
          alignItems: "flex-start",
          gap: 16,
          flexWrap: "wrap",
        }}
      >
        <div>
          <h1>Your strengths</h1>
          {assessment.data && (
            <p className="muted" style={{ fontSize: 13, margin: 0 }}>
              From profile version {assessment.data.profile_version} · {assessment.data.model_id} ·
              prompt {assessment.data.template_version} ·{" "}
              {new Date(assessment.data.created_at).toLocaleString()}
            </p>
          )}
        </div>
        <Button onClick={askForEstimate} busy={busy}>
          {assessment.data ? "Re-analyse" : "Analyse with AI"}
        </Button>
      </div>

      <ErrorNote error={error} />
      {queued && (
        <p style={{ color: "var(--status-good)", fontSize: 13.5 }}>
          <span aria-hidden="true">✓</span> Queued. This runs on your model —
          reload in a moment.
        </p>
      )}

      {estimate && (
        <div className="card" style={{ maxWidth: 620, marginTop: 12 }}>
          <h3 style={{ marginTop: 0 }}>Before we spend anything</h3>
          <p className="secondary" style={{ fontSize: 14 }}>
            This will cost about <strong>${estimate.cost_usd}</strong> on{" "}
            {estimate.model_id}, charged to your own provider.
            {estimate.rate_is_published === false && (
              <>
                {" "}
                We have no published price for that model, so this is a
                deliberately high guess.
              </>
            )}
          </p>
          <div style={{ display: "flex", gap: 8 }}>
            <Button onClick={confirm} busy={busy}>
              Run it
            </Button>
            <Button variant="secondary" onClick={() => setEstimate(null)}>
              Cancel
            </Button>
          </div>
        </div>
      )}

      {assessment.loading ? (
        <Loading what="your analysis" />
      ) : !assessment.data ? (
        <EmptyState title="No analysis yet">
          Connect a source or upload a resume, then run the analysis.
        </EmptyState>
      ) : (
        <div
          style={{
            display: "grid",
            gridTemplateColumns: "minmax(0, 1fr) minmax(0, 320px)",
            gap: 24,
            marginTop: 16,
            alignItems: "start",
          }}
        >
          <div className="card">
            <SkillRadar
              dimensions={dimensions}
              onSelect={setSelected}
              selectedKey={selected}
            />
          </div>
          <div className="card">
            {active ? (
              <>
                <h3 style={{ marginTop: 0 }}>{active.name}</h3>
                <p className="secondary" style={{ fontSize: 14 }}>
                  {active.score}/100 · confidence{" "}
                  {(active.confidence * 100).toFixed(0)}%
                </p>
                <p style={{ fontSize: 14 }}>{active.read}</p>
                <h4 style={{ fontSize: 13, marginBottom: 6 }}>Built from</h4>
                <ul style={{ fontSize: 13, margin: 0, paddingLeft: 18 }}>
                  {active.evidence_ids.map((id) => {
                    const item = byId.get(id);
                    return (
                      <li key={id} style={{ marginBottom: 6 }}>
                        <span className="muted">{item?.reference ?? "evidence"}</span>
                        {item ? ` — ${item.fact}` : ""}
                      </li>
                    );
                  })}
                </ul>
              </>
            ) : (
              <p className="muted" style={{ fontSize: 13.5 }}>
                Select a point on the radar to see what it was built from.
              </p>
            )}
          </div>
        </div>
      )}
    </section>
  );
}
