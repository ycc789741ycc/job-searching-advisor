import { useEffect, useRef, useState } from "react";
import { api } from "../api/client";
import type {
  Plan,
  PlanEstimate,
  PlanGap,
  PlanSummary,
  TargetKind,
  TargetOption,
} from "../api/types";
import {
  AutoGrid,
  Button,
  EmptyState,
  ErrorNote,
  Eyebrow,
  Loading,
  PillToggle,
  ProgressBar,
  RoundCheck,
  YouVsBar,
} from "../components/ui";
import { modelName, useShell } from "../shell/ShellContext";
import { useToast } from "../shell/toast";
import { CostConfirm } from "./CostConfirm";
import { ago } from "./time";
import { messageOf, useAsync } from "./useAsync";

type Mode = "matched" | "custom";
type Ref = { kind: TargetKind; id: string };

/** How often a drafting plan is re-read. */
const POLL_MS = 2000;

const SAMPLE_JD = {
  title: "Staff Platform Engineer",
  company: "Meridian Labs",
  text: "Staff Platform Engineer at Meridian Labs — set technical direction across three product teams, own the reliability roadmap and its SLOs, mentor senior engineers. Requires demonstrated org-level influence.",
};

/**
 * The gap plan: plan a route to one Target, then work through it.
 *
 * A plan is drafted by a background job on the user's key, so the page asks
 * for a price first, then polls the plan until it is ready or says why it
 * failed (ADR 0006). Plans are kept per Target; the history reopens them.
 */
export function GapPlan() {
  const { status, handoff, setTarget, navigate } = useShell();
  const flash = useToast();
  const model = modelName(status.credential);
  const targets = useAsync<TargetOption[]>(() => api.get("/targets"), []);
  const history = useAsync<PlanSummary[]>(() => api.get("/gap-plans"), []);

  const [mode, setMode] = useState<Mode>("matched");
  const [selected, setSelected] = useState<Ref | null>(null);
  const [planId, setPlanId] = useState<string | null>(null);
  const [plan, setPlan] = useState<Plan | null>(null);
  const [jd, setJd] = useState({ text: "", title: "", company: "" });
  const [estimate, setEstimate] = useState<{
    ref: Ref;
    label: string;
    cost: PlanEstimate;
  } | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const wasDrafting = useRef(false);
  // The first plan is opened for the user once; after that they choose.
  const opened = useRef(false);

  const options = targets.data ?? [];
  const matched = options.filter((o) => o.kind !== "privatePosting");
  const pasted = options.filter((o) => o.kind === "privatePosting");

  // Open the latest plan, unless the role map handed over a role to plan for.
  useEffect(() => {
    if (opened.current || !history.data || !targets.data) return;
    opened.current = true;
    const wanted = handoff?.roleId
      ? targets.data.find((o) => o.role_id === handoff.roleId)
      : undefined;
    if (wanted) {
      setSelected({ kind: wanted.kind, id: wanted.id });
      const existing = history.data.find(
        (p) => p.target.kind === wanted.kind && p.target.id === wanted.id,
      );
      if (existing) setPlanId(existing.id);
      return;
    }
    const latest = history.data[0];
    if (latest) {
      setPlanId(latest.id);
      setSelected(latest.target);
      setMode(latest.target.kind === "privatePosting" ? "custom" : "matched");
    } else if (targets.data[0]) {
      setSelected({ kind: targets.data[0].kind, id: targets.data[0].id });
    }
  }, [history.data, targets.data, handoff]);

  // Read the open plan, and keep re-reading it while it is being drafted.
  useEffect(() => {
    if (!planId) return;
    let cancelled = false;
    let timer: ReturnType<typeof setTimeout> | undefined;
    const load = async () => {
      try {
        const next = await api.get<Plan>(`/gap-plans/${planId}`);
        if (cancelled) return;
        setPlan(next);
        if (next.status === "drafting") {
          wasDrafting.current = true;
          timer = setTimeout(load, POLL_MS);
        } else if (wasDrafting.current) {
          wasDrafting.current = false;
          void history.reload();
          void targets.reload();
          flash(
            next.status === "ready"
              ? `${next.model_id ?? model} drafted a plan for ${next.label}.`
              : "Drafting failed — the reason is on the page.",
          );
        }
      } catch (caught) {
        if (!cancelled) setError(messageOf(caught));
      }
    };
    void load();
    return () => {
      cancelled = true;
      if (timer) clearTimeout(timer);
    };
    // history/targets reloads are stable enough; re-running on them would
    // restart polling for no reason.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [planId]);

  // The header's target chip names what this plan aims at.
  useEffect(() => {
    const fit = plan?.snapshot?.fit;
    setTarget(plan ? `${plan.label}${fit != null ? ` · ${fit}%` : ""}` : null);
    return () => setTarget(null);
  }, [plan, setTarget]);

  /** Picking a Target shows its latest plan, or none yet. */
  function selectTarget(ref: Ref) {
    opened.current = true;
    setSelected(ref);
    const existing = (history.data ?? []).find(
      (p) => p.target.kind === ref.kind && p.target.id === ref.id,
    );
    if (existing?.id !== planId) {
      setPlan(null);
      setPlanId(existing?.id ?? null);
    }
  }

  async function price(ref: Ref, label: string) {
    setBusy(true);
    setError(null);
    try {
      const cost = await api.get<PlanEstimate>(
        `/gap-plans/cost-estimate?kind=${ref.kind}&id=${ref.id}`,
      );
      setEstimate({ ref, label, cost });
    } catch (caught) {
      setError(messageOf(caught));
    } finally {
      setBusy(false);
    }
  }

  async function generate() {
    if (!status.credential) {
      flash("Plan drafting runs on your model — add a key.");
      navigate("model");
      return;
    }
    if (mode === "custom" && jd.text.trim()) {
      if (!jd.title.trim() || !jd.company.trim()) {
        setError("Give the posting a title and a company first.");
        return;
      }
      setBusy(true);
      setError(null);
      try {
        const posting = await api.post<{ id: string }>("/job-descriptions", {
          company_name: jd.company.trim(),
          title: jd.title.trim(),
          location: null,
          description: jd.text,
        });
        setJd({ text: "", title: "", company: "" });
        await targets.reload();
        const ref: Ref = { kind: "privatePosting", id: posting.id };
        selectTarget(ref);
        await price(ref, `${jd.title.trim()} · ${jd.company.trim()}`);
      } catch (caught) {
        setError(messageOf(caught));
        setBusy(false);
      }
      return;
    }
    const option = options.find(
      (o) => o.kind === selected?.kind && o.id === selected?.id,
    );
    if (!option) {
      setError(
        mode === "custom"
          ? "Paste the job description first."
          : "Pick a role to plan a route to.",
      );
      return;
    }
    await price({ kind: option.kind, id: option.id }, option.label);
  }

  async function confirm() {
    if (!estimate) return;
    setBusy(true);
    setError(null);
    try {
      const created = await api.post<PlanSummary>("/gap-plans", estimate.ref);
      setEstimate(null);
      setPlan(null);
      setPlanId(created.id);
      void history.reload();
    } catch (caught) {
      setError(messageOf(caught));
    } finally {
      setBusy(false);
    }
  }

  async function toggleTask(taskId: string, done: boolean) {
    if (!plan) return;
    // Optimistic: the tick shows at once, and the plan is re-read for progress.
    setPlan({
      ...plan,
      milestones: plan.milestones.map((m) => ({
        ...m,
        tasks: m.tasks.map((t) => (t.id === taskId ? { ...t, done } : t)),
      })),
    });
    try {
      await api.put(`/gap-plan-tasks/${taskId}`, { done });
      setPlan(await api.get<Plan>(`/gap-plans/${plan.id}`));
      void history.reload();
    } catch (caught) {
      setError(messageOf(caught));
      setPlan(await api.get<Plan>(`/gap-plans/${plan.id}`));
    }
  }

  function revisit(entry: PlanSummary) {
    opened.current = true;
    setSelected(entry.target);
    setMode(entry.target.kind === "privatePosting" ? "custom" : "matched");
    setPlan(null);
    setPlanId(entry.id);
    flash(`Revisiting the ${entry.label.split(" · ").pop()} plan.`);
  }

  const planTarget = plan
    ? (plan.snapshot?.role_name ?? plan.snapshot?.title ?? plan.label)
    : null;
  const doneCount =
    plan?.milestones.flatMap((m) => m.tasks).filter((t) => t.done).length ?? 0;

  return (
    <section>
      <div className="panel panel-tight" style={{ marginBottom: 20 }}>
        <AutoGrid col={300} gap={22}>
          <div>
            <div className="row">
              <Eyebrow>Plan a route to</Eyebrow>
              <PillToggle
                small
                pressed={mode === "matched"}
                onClick={() => setMode("matched")}
              >
                Matched &amp; subscribed
              </PillToggle>
              <PillToggle
                small
                pressed={mode === "custom"}
                onClick={() => setMode("custom")}
              >
                My own JD
              </PillToggle>
            </div>
            <p className="subcopy" style={{ margin: "6px 0 12px" }}>
              {mode === "matched"
                ? "Pick one of your top matched roles, or a role you subscribed to — the plan closes the distance to that role at that company."
                : "Paste a posting and the gaps, milestones and tasks below are planned against its own requirements."}
            </p>

            {targets.loading ? (
              <Loading what="your targets" />
            ) : mode === "matched" ? (
              matched.length === 0 ? (
                <p className="subcopy">
                  No matched roles yet.{" "}
                  <button
                    type="button"
                    className="btn btn-ghost"
                    onClick={() => navigate("roles")}
                  >
                    Build your role map
                  </button>{" "}
                  or paste a JD instead.
                </p>
              ) : (
                <TargetChips
                  options={matched}
                  selected={selected}
                  onSelect={selectTarget}
                />
              )
            ) : (
              <>
                {pasted.length > 0 && (
                  <div style={{ marginBottom: 12 }}>
                    <TargetChips
                      options={pasted}
                      selected={selected}
                      onSelect={(ref) => {
                        selectTarget(ref);
                        setJd({ text: "", title: "", company: "" });
                      }}
                    />
                  </div>
                )}
                <textarea
                  className="input"
                  rows={6}
                  aria-label="Job description"
                  value={jd.text}
                  placeholder={`Paste the job description — ${model} reads its requirements and plans the milestones against them.`}
                  onChange={(event) =>
                    setJd({ ...jd, text: event.target.value })
                  }
                />
                <div
                  className="row"
                  style={{ marginTop: 10, flexWrap: "wrap" }}
                >
                  <input
                    className="input"
                    aria-label="Job title"
                    placeholder="Job title"
                    style={{ flex: "1 1 150px", width: "auto" }}
                    value={jd.title}
                    onChange={(event) =>
                      setJd({ ...jd, title: event.target.value })
                    }
                  />
                  <input
                    className="input"
                    aria-label="Company"
                    placeholder="Company"
                    style={{ flex: "1 1 150px", width: "auto" }}
                    value={jd.company}
                    onChange={(event) =>
                      setJd({ ...jd, company: event.target.value })
                    }
                  />
                  <Button
                    variant="secondary"
                    onClick={() =>
                      setJd({
                        text: SAMPLE_JD.text,
                        title: SAMPLE_JD.title,
                        company: SAMPLE_JD.company,
                      })
                    }
                  >
                    Use a sample
                  </Button>
                </div>
                <p className="subcopy" style={{ fontSize: 12.5, marginTop: 8 }}>
                  {jd.text.trim()
                    ? "Its requirements are read on your model when you generate, and it stays private to you."
                    : "Nothing read yet — paste the posting text."}
                </p>
              </>
            )}

            <div className="row" style={{ marginTop: 16 }}>
              <Button onClick={() => void generate()} busy={busy}>
                Generate gap plan
              </Button>
              {plan && (
                <span className="muted" style={{ fontSize: 12.5 }}>
                  Last generated{" "}
                  {plan.drafted_at
                    ? ago(plan.drafted_at)
                    : ago(plan.created_at)}
                </span>
              )}
            </div>
            <ErrorNote error={error} />
          </div>

          <div className="inset" style={{ padding: 18 }}>
            <Eyebrow style={{ marginBottom: 4 }}>Plan history</Eyebrow>
            {history.loading ? (
              <Loading what="your plans" />
            ) : (history.data ?? []).length === 0 ? (
              <p className="subcopy" style={{ margin: "8px 0 0" }}>
                No plans yet. The first one you generate is kept here.
              </p>
            ) : (
              (history.data ?? []).map((entry) => (
                <div
                  key={entry.id}
                  className="history-row"
                  aria-current={
                    plan &&
                    plan.target.kind === entry.target.kind &&
                    plan.target.id === entry.target.id
                      ? "true"
                      : undefined
                  }
                >
                  <div style={{ flex: 1, minWidth: 0 }}>
                    <div className="history-name">{entry.label}</div>
                    <div className="muted" style={{ fontSize: 12 }}>
                      {entry.status === "drafting"
                        ? "Drafting…"
                        : entry.status === "failed"
                          ? "Drafting failed"
                          : `Generated ${ago(entry.drafted_at ?? entry.created_at)} · ${entry.progress}% done`}
                    </div>
                  </div>
                  <Button variant="ghost" onClick={() => revisit(entry)}>
                    Revisit
                  </Button>
                </div>
              ))
            )}
            <p style={{ fontSize: 12.5, margin: "10px 0 0" }}>
              Plans are kept per role and company — reopen one to pick the
              milestones back up where you left them.
            </p>
          </div>
        </AutoGrid>
      </div>

      {estimate && (
        <CostConfirm
          busy={busy}
          onConfirm={() => void confirm()}
          onCancel={() => setEstimate(null)}
        >
          Drafting a plan for <strong>{estimate.label}</strong> costs about{" "}
          <strong>${estimate.cost.cost_usd}</strong> on {estimate.cost.model_id}
          , charged to your own provider.
          {estimate.cost.includes_scoring &&
            " That includes reading and scoring the pasted job description, which happens once."}
          {estimate.cost.rate_is_published === false &&
            " We have no published price for that model, so this is a deliberately high guess."}
        </CostConfirm>
      )}

      {!plan ? (
        planId ? (
          <Loading what="the plan" />
        ) : (
          <EmptyState title="No plan yet">
            Pick a role above, or paste a job description, and generate a plan.
            It is drafted on your model from your own evidence.
          </EmptyState>
        )
      ) : plan.status === "drafting" ? (
        <div className="panel" role="status">
          <span className="model-pill">
            Drafting on {model} for {plan.label}…
          </span>
          <p className="subcopy" style={{ marginTop: 12, marginBottom: 0 }}>
            Reading the gaps against your evidence and laying out milestones.
            This usually takes under a minute; the page updates itself.
          </p>
        </div>
      ) : plan.status === "failed" ? (
        <div className="panel">
          <h3>This plan could not be drafted</h3>
          <ErrorNote error={plan.error?.message ?? "Drafting failed."} />
          <FailureHint
            code={plan.error?.code}
            onNavigate={(screen) => navigate(screen)}
          />
        </div>
      ) : (
        <>
          <span className="model-pill" style={{ marginBottom: 16 }}>
            Drafted by {plan.model_id ?? model} for {plan.label}
            {plan.snapshot?.fit != null &&
              ` · ${plan.snapshot.fit}% fit today`}{" "}
            ·{" "}
            <button
              type="button"
              onClick={() => void price(plan.target, plan.label)}
              style={{
                all: "unset",
                cursor: "pointer",
                textDecoration: "underline",
              }}
            >
              regenerate
            </button>
          </span>

          <AutoGrid col={380} gap={20}>
            <div className="panel">
              <h3>
                The{" "}
                {plan.gaps.length === 1
                  ? "one thing"
                  : `${numberWord(plan.gaps.length)} things`}{" "}
                between you and {planTarget}
              </h3>
              <p className="subcopy" style={{ marginBottom: 14 }}>
                Ranked by how much each moves your fit score. Every line cites
                the work it was read from.
                {plan.snapshot?.basis === "posting"
                  ? " Requirements read from the posting itself."
                  : " Requirements are the role's, across its openings."}
              </p>
              {plan.gaps.map((gap, index) => (
                <GapCard key={gap.key} gap={gap} rank={index + 1} />
              ))}

              {plan.stepping_stones.length > 0 && (
                <div className="callout" style={{ padding: 18, marginTop: 16 }}>
                  <Eyebrow>
                    Stepping stones — if the jump is too far right now
                  </Eyebrow>
                  <div className="divided">
                    {plan.stepping_stones.map((stone) => (
                      <div
                        key={stone.role_id}
                        className="row-between"
                        style={{ padding: "10px 0" }}
                      >
                        <div>
                          <div style={{ fontSize: 14, fontWeight: 700 }}>
                            {stone.name}
                          </div>
                          <div
                            className="callout-note"
                            style={{ fontSize: 12.5 }}
                          >
                            {stone.openings} open roles · a credible 12-month
                            bridge
                          </div>
                        </div>
                        <span style={{ fontSize: 13, fontWeight: 700 }}>
                          {stone.fit}% fit
                        </span>
                      </div>
                    ))}
                  </div>
                </div>
              )}
            </div>

            <div className="panel">
              <div className="row-between" style={{ marginBottom: 8 }}>
                <h3 style={{ margin: 0 }}>Milestones &amp; tasks</h3>
                <span
                  style={{
                    fontSize: 13,
                    fontWeight: 700,
                    color: "var(--color-accent-700)",
                  }}
                >
                  {plan.progress}% done
                </span>
              </div>
              <div style={{ marginBottom: 18 }}>
                <ProgressBar percent={plan.progress} label="Plan progress" />
              </div>
              {plan.milestones.map((milestone) => (
                <div key={milestone.id} className="milestone">
                  <div className="row-between">
                    <span className="milestone-title">{milestone.title}</span>
                    <span className="milestone-window">{milestone.window}</span>
                  </div>
                  <p className="milestone-outcome">{milestone.outcome}</p>
                  {milestone.tasks.map((task) => {
                    const counted = task.done || task.done_elsewhere;
                    return (
                      <div
                        key={task.id}
                        className="task-row"
                        data-done={counted}
                      >
                        <RoundCheck
                          checked={counted}
                          // Toggles this plan's own tick; one counted from
                          // another plan is ticked here explicitly on click.
                          onChange={() => void toggleTask(task.id, !task.done)}
                        >
                          <span className="task-text">{task.text}</span>
                          {task.done_elsewhere && (
                            <span
                              className="muted"
                              style={{ display: "block", fontSize: 12 }}
                            >
                              Done in another plan — it counts here too.
                            </span>
                          )}
                        </RoundCheck>
                        <span className="task-due">{task.due}</span>
                      </div>
                    );
                  })}
                </div>
              ))}
              {doneCount === 0 && plan.milestones.length > 0 && (
                <p className="subcopy" style={{ marginTop: -8 }}>
                  Tick a task when it is done. Real work shows up in your
                  sources at the next sync, and the next analysis scores it.
                </p>
              )}

              {plan.projects.length > 0 && (
                <div className="inset" style={{ padding: 18 }}>
                  <Eyebrow>
                    Build one of these — it produces the evidence you&apos;re
                    missing
                  </Eyebrow>
                  <div className="divided">
                    {plan.projects.map((project) => (
                      <div key={project.name} style={{ padding: "11px 0" }}>
                        <div style={{ fontSize: 14, fontWeight: 700 }}>
                          {project.name}
                        </div>
                        <div className="subcopy" style={{ fontSize: 12.5 }}>
                          {project.note}
                        </div>
                      </div>
                    ))}
                  </div>
                </div>
              )}

              {plan.versions.length > 1 && (
                <p className="muted" style={{ fontSize: 12.5, marginTop: 14 }}>
                  Version {plan.version} of {plan.versions.length}. Finished
                  tasks carry into each new version.
                </p>
              )}
            </div>
          </AutoGrid>
        </>
      )}
    </section>
  );
}

function TargetChips({
  options,
  selected,
  onSelect,
}: {
  options: TargetOption[];
  selected: Ref | null;
  onSelect: (ref: Ref) => void;
}) {
  return (
    <div className="row" style={{ gap: 8 }}>
      {options.map((option) => (
        <button
          key={`${option.kind}:${option.id}`}
          type="button"
          className="target-chip"
          aria-pressed={
            selected?.kind === option.kind && selected.id === option.id
          }
          onClick={() => onSelect({ kind: option.kind, id: option.id })}
        >
          <b>{option.role_name ?? option.title}</b>
          <span className="target-chip-company">{option.company_name}</span>
          {option.fit !== null && (
            <span className="target-chip-fit">{option.fit}%</span>
          )}
          {option.kind === "subscription" && (
            <span className="target-chip-tag">subscribed</span>
          )}
        </button>
      ))}
    </div>
  );
}

function GapCard({ gap, rank }: { gap: PlanGap; rank: number }) {
  return (
    <div className="gap-card">
      <div className="row-between">
        <span className="gap-card-title">
          {String(rank).padStart(2, "0")} · {gap.name}
        </span>
        <span className="gap-card-lift">+{gap.lift} fit pts</span>
      </div>
      <div style={{ margin: "12px 0" }}>
        {gap.kind === "dimension" &&
        gap.user_score !== null &&
        gap.target_score !== null ? (
          <YouVsBar
            you={gap.user_score}
            bar={gap.target_score}
            label={gap.name}
          />
        ) : (
          <span className="tag tag-neutral">No evidence at all</span>
        )}
      </div>
      <p className="gap-card-why">{gap.why}</p>
      {gap.evidence.map((item) => (
        <div key={item.id} className="gap-card-cite">
          {item.reference} — {item.fact}
        </div>
      ))}
    </div>
  );
}

function FailureHint({
  code,
  onNavigate,
}: {
  code: string | undefined;
  onNavigate: (screen: "model" | "roles") => void;
}) {
  if (code?.startsWith("ai_credential") || code === "ai_budget_exceeded") {
    return (
      <p className="subcopy">
        This is about your model or budget, not the plan.{" "}
        <Button variant="ghost" onClick={() => onNavigate("model")}>
          Open AI &amp; model
        </Button>
      </p>
    );
  }
  if (code === "target_unusable") {
    return (
      <p className="subcopy">
        <Button variant="ghost" onClick={() => onNavigate("roles")}>
          Back to the role map
        </Button>
      </p>
    );
  }
  return (
    <p className="subcopy">
      No plan was drafted this time. Regenerating tries again as a fresh
      version.
    </p>
  );
}

const WORDS = ["zero", "one", "two", "three", "four", "five", "six"];

function numberWord(n: number): string {
  return WORDS[n] ?? String(n);
}
