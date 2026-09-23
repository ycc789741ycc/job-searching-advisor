import { useEffect, useRef, useState } from "react";
import { api, streamEvents } from "../api/client";
import type {
  PlanEstimate,
  ResumeContent,
  ResumeExport,
  ResumeOptions,
  ResumeSummary,
  ResumeTemplate,
  ResumeVersion,
  Subscription,
  TailoredResume,
  TargetKind,
  TargetOption,
} from "../api/types";
import {
  AutoGrid,
  Button,
  EmptyState,
  ErrorNote,
  Eyebrow,
  FitBadge,
  Loading,
  PillToggle,
  RoundCheck,
  VerdictBadge,
} from "../components/ui";
import { modelName, useShell } from "../shell/ShellContext";
import { useToast } from "../shell/toast";
import { CostConfirm } from "./CostConfirm";
import { ago } from "./time";
import { messageOf, useAsync } from "./useAsync";

type Mode = "matched" | "custom";
type Ref = { kind: TargetKind; id: string };

const POLL_MS = 2000;

/** Crawl source kinds as the filter pills name them (domain decision 6). */
const SOURCE_LABELS: Record<string, string> = {
  atsBoard: "ATS board",
  jsonLd: "Careers page",
  publicApi: "Public job API",
  watchlist: "Watchlist",
  pasted: "Your JD",
};
const FILTERS = [
  "all",
  "atsBoard",
  "jsonLd",
  "publicApi",
  "watchlist",
] as const;
type Filter = (typeof FILTERS)[number];

const TEMPLATES: {
  id: ResumeTemplate;
  name: string;
  note: string;
  swatch: string;
  color: string;
  rule: string;
}[] = [
  {
    id: "warm",
    name: "Warm",
    note: "Rounded, terracotta rule.",
    swatch: "#c67139",
    color: "#8a4a20",
    rule: "3px solid #c67139",
  },
  {
    id: "plain",
    name: "Plain",
    note: "ATS-safe, no ornament.",
    swatch: "#9b9691",
    color: "#201e1d",
    rule: "1px solid #cfcac5",
  },
  {
    id: "brief",
    name: "Brief",
    note: "One page, evidence first.",
    swatch: "#7a8a5e",
    color: "#4d5a35",
    rule: "3px solid #7a8a5e",
  },
];

const OPTION_LABELS: { key: keyof ResumeOptions; label: string }[] = [
  { key: "metrics", label: "Quantify bullets with data from Jira and GitHub" },
  { key: "reorder", label: "Reorder skills by what this role screens for" },
  { key: "trim", label: "Trim to one page" },
];

const SUGGESTIONS = [
  "Make the summary shorter",
  "Quantify every bullet",
  "Answer their top requirement first",
];

const SAMPLE_JD = {
  title: "Staff Platform Engineer",
  company: "Meridian Labs",
  text: "Staff Platform Engineer — you will set technical direction across three product teams, own the reliability roadmap, and mentor senior engineers. Requires demonstrated org-level influence and SLO ownership.",
};

interface Exchange {
  request: string;
  reply: string;
  revisionId: string | null;
  hasProposal: boolean;
  applied: boolean;
  error: string | null;
  streaming: boolean;
}

/**
 * The Resume Advisor: written for one Target at a time.
 *
 * The first version is written on the user's key from their cited evidence;
 * the page polls it while it is being written (ADR 0006). The page is then
 * edited in place, saved as versions, revised through a streamed chat whose
 * proposals apply only on request, and exported as a PDF.
 */
export function Resume() {
  const { status, handoff, setTarget, navigate } = useShell();
  const flash = useToast();
  const model = modelName(status.credential);
  const targets = useAsync<TargetOption[]>(() => api.get("/targets"), []);
  const saved = useAsync<ResumeSummary[]>(
    () => api.get("/tailored-resumes"),
    [],
  );

  const [mode, setMode] = useState<Mode>("matched");
  const [filter, setFilter] = useState<Filter>("all");
  const [selected, setSelected] = useState<Ref | null>(null);
  const [resumeId, setResumeId] = useState<string | null>(null);
  const [resume, setResume] = useState<TailoredResume | null>(null);
  const [draft, setDraft] = useState<ResumeContent | null>(null);
  const [jd, setJd] = useState({ text: "", title: "", company: "" });
  const [estimate, setEstimate] = useState<{
    ref: Ref;
    label: string;
    cost: PlanEstimate;
  } | null>(null);
  const [template, setTemplate] = useState<ResumeTemplate>("warm");
  const [options, setOptions] = useState<ResumeOptions>({
    metrics: true,
    reorder: true,
    trim: false,
  });
  const [exchanges, setExchanges] = useState<Exchange[]>([]);
  const [exporting, setExporting] = useState<ResumeExport | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const opened = useRef(false);
  const wasDrafting = useRef(false);

  const targetOptions = targets.data ?? [];
  const optionOf = (ref: Ref | null) =>
    targetOptions.find((o) => o.kind === ref?.kind && o.id === ref?.id);
  const ranked = targetOptions.filter(
    (o) =>
      o.kind !== "privatePosting" &&
      (filter === "all" || o.source_kind === filter),
  );
  const pasted = targetOptions.filter((o) => o.kind === "privatePosting");
  const dirty =
    !!draft &&
    !!resume?.content &&
    JSON.stringify(draft) !== JSON.stringify(resume.content);

  // Open the most recent résumé, unless the role map handed over a role.
  useEffect(() => {
    if (opened.current || !saved.data || !targets.data) return;
    opened.current = true;
    const wanted = handoff?.roleId
      ? targets.data.find((o) => o.role_id === handoff.roleId)
      : undefined;
    if (wanted) {
      pick({ kind: wanted.kind, id: wanted.id }, saved.data);
      return;
    }
    const latest = saved.data[0];
    if (latest) {
      setSelected(latest.target);
      setMode(latest.target.kind === "privatePosting" ? "custom" : "matched");
      setResumeId(latest.id);
    } else if (targets.data[0]) {
      setSelected({ kind: targets.data[0].kind, id: targets.data[0].id });
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [saved.data, targets.data, handoff]);

  // Read the open résumé, and keep re-reading it while it is being written.
  useEffect(() => {
    if (!resumeId) return;
    let cancelled = false;
    let timer: ReturnType<typeof setTimeout> | undefined;
    const load = async () => {
      try {
        const next = await api.get<TailoredResume>(
          `/tailored-resumes/${resumeId}`,
        );
        if (cancelled) return;
        show(next);
        if (next.status === "drafting") {
          wasDrafting.current = true;
          timer = setTimeout(load, POLL_MS);
        } else if (wasDrafting.current) {
          wasDrafting.current = false;
          void saved.reload();
          void targets.reload();
          flash(
            next.status === "ready"
              ? `Written for ${next.label}.`
              : "Writing failed — the reason is on the page.",
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
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [resumeId]);

  useEffect(() => {
    const fit = resume?.snapshot?.fit;
    setTarget(
      resume ? `${resume.label}${fit != null ? ` · ${fit}%` : ""}` : null,
    );
    return () => setTarget(null);
  }, [resume, setTarget]);

  function show(next: TailoredResume) {
    setResume(next);
    setDraft(next.content);
    setTemplate(next.template);
    setOptions(next.options);
    setExchanges(
      next.revisions.map((r) => ({
        request: r.request,
        reply: r.reply,
        revisionId: r.id,
        hasProposal: r.has_proposal,
        applied: r.applied_version_id !== null,
        error: null,
        streaming: false,
      })),
    );
  }

  /** Picking a Target opens its latest résumé, or none yet. */
  function pick(ref: Ref, list = saved.data ?? []) {
    opened.current = true;
    setSelected(ref);
    const existing = list.find(
      (r) => r.target.kind === ref.kind && r.target.id === ref.id,
    );
    if (existing?.id !== resumeId) {
      setResume(null);
      setDraft(null);
      setExchanges([]);
      setResumeId(existing?.id ?? null);
    }
  }

  async function price(ref: Ref, label: string) {
    if (!status.credential) {
      flash("Writing runs on your model — add a key.");
      navigate("model");
      return;
    }
    setBusy(true);
    setError(null);
    try {
      const cost = await api.get<PlanEstimate>(
        `/tailored-resumes/cost-estimate?kind=${ref.kind}&id=${ref.id}`,
      );
      setEstimate({ ref, label, cost });
    } catch (caught) {
      setError(messageOf(caught));
    } finally {
      setBusy(false);
    }
  }

  async function scoreAndWrite() {
    if (!jd.text.trim()) {
      setError("Paste the job description first.");
      return;
    }
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
      const label = `${jd.title.trim()} · ${jd.company.trim()}`;
      setJd({ text: "", title: "", company: "" });
      await targets.reload();
      const ref: Ref = { kind: "privatePosting", id: posting.id };
      pick(ref);
      await price(ref, label);
    } catch (caught) {
      setError(messageOf(caught));
      setBusy(false);
    }
  }

  async function write() {
    if (!estimate) return;
    setBusy(true);
    setError(null);
    try {
      const created = await api.post<ResumeSummary>("/tailored-resumes", {
        ...estimate.ref,
        template,
        options,
      });
      setEstimate(null);
      setResume(null);
      setDraft(null);
      setExchanges([]);
      setResumeId(created.id);
      void saved.reload();
    } catch (caught) {
      setError(messageOf(caught));
    } finally {
      setBusy(false);
    }
  }

  async function saveVersion() {
    if (!resume || !draft) return;
    setBusy(true);
    setError(null);
    try {
      const version = await api.post<ResumeVersion>(
        `/tailored-resumes/${resume.id}/versions`,
        { content: draft },
      );
      show(await api.get<TailoredResume>(`/tailored-resumes/${resume.id}`));
      void saved.reload();
      flash(`Saved version ${version.number} of “${resume.label}”.`);
    } catch (caught) {
      setError(messageOf(caught));
    } finally {
      setBusy(false);
    }
  }

  async function changeSettings(
    nextTemplate: ResumeTemplate,
    nextOptions: ResumeOptions,
  ) {
    setTemplate(nextTemplate);
    setOptions(nextOptions);
    if (!resume || resume.status !== "ready") return;
    try {
      await api.put(`/tailored-resumes/${resume.id}/settings`, {
        template: nextTemplate,
        options: nextOptions,
      });
    } catch (caught) {
      setError(messageOf(caught));
    }
  }

  async function exportPdf() {
    if (!resume?.version) return;
    setError(null);
    try {
      let job = await api.post<ResumeExport>(
        `/tailored-resumes/${resume.id}/exports`,
        { version: resume.version.number },
      );
      setExporting(job);
      while (job.status === "rendering") {
        await new Promise((resolve) => setTimeout(resolve, POLL_MS));
        job = await api.get<ResumeExport>(`/resume-exports/${job.id}`);
        setExporting(job);
      }
      if (job.status === "ready" && job.download_url) {
        flash(`Exported — ${resume.label}, ${template} template.`);
      }
    } catch (caught) {
      setError(messageOf(caught));
      setExporting(null);
    }
  }

  async function send(message: string) {
    if (!resume || !draft || !message.trim()) return;
    const index = exchanges.length;
    setExchanges((all) => [
      ...all,
      {
        request: message,
        reply: "",
        revisionId: null,
        hasProposal: false,
        applied: false,
        error: null,
        streaming: true,
      },
    ]);
    const update = (change: Partial<Exchange>) =>
      setExchanges((all) =>
        all.map((e, i) => (i === index ? { ...e, ...change } : e)),
      );
    try {
      await streamEvents(
        `/tailored-resumes/${resume.id}/revisions`,
        { message, content: draft },
        (event) => {
          const data = JSON.parse(event.data) as Record<string, unknown>;
          if (event.event === "text") {
            setExchanges((all) =>
              all.map((e, i) =>
                i === index ? { ...e, reply: e.reply + String(data.text) } : e,
              ),
            );
          } else if (event.event === "proposal") {
            update({
              revisionId: String(data.revision_id),
              hasProposal: data.proposal !== null,
              reply: String(data.reply),
            });
          } else if (event.event === "error") {
            update({ error: String(data.message) });
          }
        },
      );
    } catch (caught) {
      update({ error: messageOf(caught) });
    } finally {
      update({ streaming: false });
    }
  }

  async function apply(revisionId: string) {
    if (!resume) return;
    try {
      const version = await api.post<ResumeVersion>(
        `/tailored-resumes/${resume.id}/revisions/${revisionId}/apply`,
      );
      show(await api.get<TailoredResume>(`/tailored-resumes/${resume.id}`));
      void saved.reload();
      flash(`Applied as version ${version.number}.`);
    } catch (caught) {
      setError(messageOf(caught));
    }
  }

  const current = optionOf(selected);
  const targetLine = resume
    ? `${resume.label}${resume.snapshot?.fit != null ? ` · ${resume.snapshot.fit}% fit` : ""}`
    : current
      ? `${current.label}${current.fit !== null ? ` · ${current.fit}% fit` : ""}`
      : mode === "custom"
        ? "Paste a job description to begin"
        : "Pick a role to write for";
  const watchCount = targetOptions.filter(
    (o) => o.kind === "subscription",
  ).length;

  return (
    <section>
      <div className="panel panel-tight" style={{ marginBottom: 20 }}>
        <div
          className="row-between"
          style={{ alignItems: "flex-end", flexWrap: "wrap", marginBottom: 14 }}
        >
          <div>
            <Eyebrow>Write for</Eyebrow>
            <div
              style={{
                fontFamily: "var(--font-heading)",
                fontSize: 20,
                marginTop: 4,
              }}
            >
              {targetLine}
            </div>
          </div>
          <div className="row">
            <PillToggle
              pressed={mode === "matched"}
              onClick={() => setMode("matched")}
            >
              Top matched roles
            </PillToggle>
            <PillToggle
              pressed={mode === "custom"}
              onClick={() => setMode("custom")}
            >
              My own JD
            </PillToggle>
          </div>
        </div>

        {mode === "matched" ? (
          <>
            <div className="row" style={{ gap: 7, marginBottom: 12 }}>
              {FILTERS.map((f) => (
                <PillToggle
                  key={f}
                  small
                  pressed={filter === f}
                  onClick={() => setFilter(f)}
                >
                  {f === "all" ? "All" : SOURCE_LABELS[f]}
                </PillToggle>
              ))}
              <span className="subcopy" style={{ fontSize: 12.5 }}>
                Ranked by your fit to each role · {watchCount} subscribed from
                your watchlist
              </span>
            </div>
            {targets.loading ? (
              <Loading what="your targets" />
            ) : ranked.length === 0 ? (
              <p className="subcopy">
                Nothing here yet.{" "}
                <Button variant="ghost" onClick={() => navigate("roles")}>
                  Build your role map
                </Button>{" "}
                or paste a JD instead.
              </p>
            ) : (
              <div
                className="stack"
                style={{
                  gap: 8,
                  maxHeight: 318,
                  overflowY: "auto",
                  paddingRight: 4,
                }}
              >
                {ranked.map((option, index) => (
                  <WriteRow
                    key={`${option.kind}:${option.id}`}
                    option={option}
                    rank={index + 1}
                    current={
                      selected?.kind === option.kind &&
                      selected.id === option.id
                    }
                    onPick={() => pick({ kind: option.kind, id: option.id })}
                    onChanged={() => void targets.reload()}
                  />
                ))}
              </div>
            )}
          </>
        ) : (
          <AutoGrid col={300} gap={18}>
            <div>
              <textarea
                className="input"
                rows={7}
                aria-label="Job description"
                value={jd.text}
                placeholder={`Paste the full job description — ${model} scores it against your profile and writes the résumé to its requirements.`}
                onChange={(event) => setJd({ ...jd, text: event.target.value })}
              />
              <div className="row" style={{ marginTop: 12 }}>
                <input
                  className="input"
                  aria-label="Job title"
                  placeholder="Job title"
                  style={{ flex: "1 1 140px", width: "auto" }}
                  value={jd.title}
                  onChange={(event) =>
                    setJd({ ...jd, title: event.target.value })
                  }
                />
                <input
                  className="input"
                  aria-label="Company"
                  placeholder="Company"
                  style={{ flex: "1 1 140px", width: "auto" }}
                  value={jd.company}
                  onChange={(event) =>
                    setJd({ ...jd, company: event.target.value })
                  }
                />
              </div>
              <div className="row" style={{ marginTop: 12 }}>
                <Button busy={busy} onClick={() => void scoreAndWrite()}>
                  Score &amp; write
                </Button>
                <Button
                  variant="ghost"
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
            </div>
            <div className="inset" style={{ padding: 18 }}>
              <Eyebrow style={{ marginBottom: 8 }}>Your pasted JDs</Eyebrow>
              {pasted.length === 0 ? (
                <p className="subcopy" style={{ margin: 0 }}>
                  A JD you paste stays private to you. Its requirements are read
                  on your model when you write for it.
                </p>
              ) : (
                <div className="stack" style={{ gap: 8 }}>
                  {pasted.map((option) => (
                    <WriteRow
                      key={option.id}
                      option={option}
                      rank={null}
                      current={
                        selected?.kind === option.kind &&
                        selected.id === option.id
                      }
                      onPick={() => pick({ kind: option.kind, id: option.id })}
                      onChanged={() => void targets.reload()}
                    />
                  ))}
                </div>
              )}
            </div>
          </AutoGrid>
        )}

        {current && !resumeId && (
          <div className="row" style={{ marginTop: 14 }}>
            <Button
              busy={busy}
              onClick={() =>
                void price(
                  { kind: current.kind, id: current.id },
                  current.label,
                )
              }
            >
              Write résumé for {current.role_name ?? current.title}
            </Button>
            <span className="subcopy">
              Written on your model from your own evidence; every line cites its
              source.
            </span>
          </div>
        )}
        <ErrorNote error={error} />
      </div>

      {estimate && (
        <CostConfirm
          busy={busy}
          onConfirm={() => void write()}
          onCancel={() => setEstimate(null)}
        >
          Writing a résumé for <strong>{estimate.label}</strong> costs about{" "}
          <strong>${estimate.cost.cost_usd}</strong> on {estimate.cost.model_id}
          , charged to your own provider.
          {estimate.cost.includes_scoring &&
            " That includes reading and scoring the pasted job description, which happens once."}
          {estimate.cost.rate_is_published === false &&
            " We have no published price for that model, so this is a deliberately high guess."}
        </CostConfirm>
      )}

      <AutoGrid col={320} gap={20}>
        <div className="stack" style={{ gap: 18 }}>
          <div className="panel panel-tight">
            <Eyebrow style={{ marginBottom: 12 }}>Saved résumés</Eyebrow>
            {(saved.data ?? []).length === 0 ? (
              <p className="subcopy" style={{ marginTop: 0 }}>
                None yet. Each one you write is kept here, with every version.
              </p>
            ) : (
              (saved.data ?? []).map((entry) => (
                <div
                  key={entry.id}
                  className="history-row inset"
                  aria-current={entry.id === resumeId ? "true" : undefined}
                  style={{ marginBottom: 6 }}
                >
                  <div style={{ flex: 1, minWidth: 0 }}>
                    <div className="history-name">{entry.label}</div>
                    <div className="muted" style={{ fontSize: 12 }}>
                      {entry.status === "drafting"
                        ? "Writing…"
                        : entry.status === "failed"
                          ? "Writing failed"
                          : `Saved ${ago(entry.updated_at)} · v${entry.latest_version ?? 1}`}
                    </div>
                  </div>
                  <Button
                    variant="ghost"
                    onClick={() => {
                      pick(entry.target);
                      setMode(
                        entry.target.kind === "privatePosting"
                          ? "custom"
                          : "matched",
                      );
                      flash(`Opened “${entry.label}”.`);
                    }}
                  >
                    Open
                  </Button>
                </div>
              ))
            )}
            <Button
              variant="secondary"
              busy={busy}
              disabled={!dirty}
              onClick={() => void saveVersion()}
            >
              Save this version
            </Button>
            {dirty && (
              <p className="subcopy" style={{ fontSize: 12.5, marginTop: 8 }}>
                You have unsaved edits.
              </p>
            )}
          </div>

          <div className="panel panel-tight">
            <Eyebrow style={{ marginBottom: 12 }}>Template</Eyebrow>
            <div className="stack" style={{ gap: 10 }}>
              {TEMPLATES.map((t) => (
                <button
                  key={t.id}
                  type="button"
                  className="template-pick"
                  aria-pressed={template === t.id}
                  onClick={() => void changeSettings(t.id, options)}
                >
                  <span className="template-thumb" aria-hidden="true">
                    <span
                      style={{ height: 5, background: t.swatch, width: "100%" }}
                    />
                    <span />
                    <span />
                    <span style={{ width: "70%" }} />
                  </span>
                  <span>
                    <span
                      style={{
                        display: "block",
                        fontFamily: "var(--font-heading)",
                        fontSize: 15,
                      }}
                    >
                      {t.name}
                    </span>
                    <span className="subcopy" style={{ fontSize: 12.5 }}>
                      {t.note}
                    </span>
                  </span>
                </button>
              ))}
            </div>
            <div className="stack" style={{ gap: 10, marginTop: 16 }}>
              {OPTION_LABELS.map(({ key, label }) => (
                <RoundCheck
                  key={key}
                  checked={options[key]}
                  onChange={(on) =>
                    void changeSettings(template, { ...options, [key]: on })
                  }
                >
                  {label}
                </RoundCheck>
              ))}
            </div>
            <Button
              block
              busy={exporting?.status === "rendering"}
              disabled={!resume?.version || dirty}
              onClick={() => void exportPdf()}
            >
              Export as PDF
            </Button>
            {exporting?.status === "ready" && exporting.download_url && (
              <p style={{ fontSize: 13, margin: "10px 0 0" }}>
                <a
                  href={exporting.download_url}
                  target="_blank"
                  rel="noreferrer"
                >
                  Download the PDF
                </a>{" "}
                <span className="muted">(the link expires shortly)</span>
              </p>
            )}
            {exporting?.status === "failed" && (
              <ErrorNote error={exporting.error?.message ?? "Export failed."} />
            )}
            <p className="subcopy" style={{ fontSize: 12.5, marginTop: 10 }}>
              {dirty
                ? "Save this version first — the export is of a saved version."
                : resume?.snapshot
                  ? `Highlighted lines were rewritten for ${resume.snapshot.role_name ?? resume.snapshot.title} at ${resume.snapshot.company}, from the sources cited under each bullet.`
                  : "The export is a white, printable page in the template you pick."}
            </p>
          </div>

          <WatchlistPanel onChanged={() => void targets.reload()} />
        </div>

        <div>
          {!resume ? (
            resumeId ? (
              <Loading what="the résumé" />
            ) : (
              <EmptyState title="No résumé for this target yet">
                Pick a role above, or paste a job description, and write one.
                The first version is customised to that role.
              </EmptyState>
            )
          ) : resume.status === "drafting" ? (
            <div className="resume-page" role="status">
              <span className="model-pill">
                Writing on {model} for {resume.label}…
              </span>
              <p className="subcopy" style={{ marginTop: 12 }}>
                Reading your evidence against their requirements. The page
                updates itself when it is done.
              </p>
            </div>
          ) : resume.status === "failed" ? (
            <div className="panel">
              <h3>This résumé could not be written</h3>
              <ErrorNote error={resume.error?.message ?? "Writing failed."} />
              {(resume.error?.code?.startsWith("ai_credential") ||
                resume.error?.code === "ai_budget_exceeded") && (
                <Button variant="ghost" onClick={() => navigate("model")}>
                  Open AI &amp; model
                </Button>
              )}
            </div>
          ) : draft ? (
            <ResumePage
              key={resume.version?.id}
              content={draft}
              evidence={resume.evidence}
              template={
                TEMPLATES.find((t) => t.id === template) ?? TEMPLATES[0]!
              }
              reorder={options.reorder}
              onChange={setDraft}
            />
          ) : null}
        </div>

        <div className="stack" style={{ gap: 18 }}>
          <div className="callout" style={{ padding: 22 }}>
            <Eyebrow>Their requirements → your evidence</Eyebrow>
            {!resume || resume.coverage.length === 0 ? (
              <p
                className="callout-note"
                style={{ fontSize: 13, margin: "10px 0 0" }}
              >
                Once a résumé is written, each of their requirements shows here
                as covered, partial or a gap, with the work that backs it.
              </p>
            ) : (
              <div className="divided">
                {resume.coverage.map((row) => (
                  <div key={row.requirement}>
                    <div
                      className="row"
                      style={{
                        gap: 8,
                        flexWrap: "nowrap",
                        alignItems: "baseline",
                      }}
                    >
                      <VerdictBadge verdict={row.verdict} />
                      <span style={{ fontSize: 13.5, fontWeight: 700 }}>
                        {row.requirement}
                      </span>
                    </div>
                    <div
                      className="callout-note"
                      style={{ fontSize: 12.5, marginTop: 5 }}
                    >
                      {row.evidence.length > 0
                        ? row.evidence
                            .map((e) => `${e.reference} — ${e.fact}`)
                            .join(" · ")
                        : "Nothing in your sources speaks to this yet."}
                    </div>
                  </div>
                ))}
              </div>
            )}
          </div>

          <ChatPanel
            model={model}
            target={
              resume?.snapshot?.role_name ?? resume?.snapshot?.title ?? null
            }
            enabled={resume?.status === "ready" && !!draft}
            exchanges={exchanges}
            onSend={(message) => void send(message)}
            onApply={(revisionId) => void apply(revisionId)}
            onDismiss={(index) =>
              setExchanges((all) =>
                all.map((e, i) =>
                  i === index ? { ...e, hasProposal: false } : e,
                ),
              )
            }
          />
        </div>
      </AutoGrid>
    </section>
  );
}

function WriteRow({
  option,
  rank,
  current,
  onPick,
  onChanged,
}: {
  option: TargetOption;
  rank: number | null;
  current: boolean;
  onPick: () => void;
  onChanged: () => void;
}) {
  const [busy, setBusy] = useState(false);
  const pay = option.salary
    ? `${option.salary.currency} ${Math.round(option.salary.min / 1000)}–${Math.round(option.salary.max / 1000)}k`
    : null;
  const detail = [
    pay,
    SOURCE_LABELS[option.source_kind ?? ""] ?? option.source_kind,
    option.kind === "matchedPosting" ? option.title : null,
  ]
    .filter(Boolean)
    .join(" · ");
  const subscribed =
    option.kind === "subscription" || option.subscription_id !== null;

  async function toggleWatch() {
    setBusy(true);
    try {
      if (option.subscription_id) {
        await api.del(`/role-subscriptions/${option.subscription_id}`);
      } else {
        await api.post("/role-subscriptions", {
          company_name: option.company_name,
          role_title: option.role_name ?? option.title,
          role_id: option.role_id,
          url: option.url,
        });
      }
      onChanged();
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="write-row" aria-current={current ? "true" : undefined}>
      <button type="button" className="write-row-pick" onClick={onPick}>
        {rank !== null && (
          <span className="write-rank">{String(rank).padStart(2, "0")}</span>
        )}
        <FitBadge fit={option.fit} />
        <span style={{ minWidth: 0 }}>
          <span
            className="ellipsis"
            style={{ display: "block", fontSize: 14, fontWeight: 700 }}
          >
            {option.role_name ?? option.title} · {option.company_name}
          </span>
          <span
            className="ellipsis subcopy"
            style={{ display: "block", fontSize: 12.5 }}
          >
            {detail}
          </span>
        </span>
      </button>
      {option.kind === "matchedPosting" && (
        <PillToggle
          small
          pressed={subscribed}
          disabled={busy}
          onClick={() => void toggleWatch()}
        >
          {subscribed ? "Subscribed" : "Subscribe"}
        </PillToggle>
      )}
    </div>
  );
}

function ResumePage({
  content,
  evidence,
  template,
  reorder,
  onChange,
}: {
  content: ResumeContent;
  evidence: TailoredResume["evidence"];
  template: (typeof TEMPLATES)[number];
  reorder: boolean;
  onChange: (next: ResumeContent) => void;
}) {
  const edit = (patch: Partial<ResumeContent>) =>
    onChange({ ...content, ...patch });

  const editBullet = (p: number, b: number, text: string) =>
    onChange({
      ...content,
      experience: content.experience.map((position, pi) =>
        pi !== p
          ? position
          : {
              ...position,
              bullets: position.bullets.map((bullet, bi) =>
                bi === b ? { ...bullet, text } : bullet,
              ),
            },
      ),
    });

  return (
    <article className="resume-page" aria-label="Résumé">
      <header
        style={{
          borderBottom: template.rule,
          paddingBottom: 14,
          marginBottom: 20,
        }}
      >
        <div
          className="resume-name"
          style={{ color: template.color }}
          contentEditable
          suppressContentEditableWarning
          aria-label="Name"
          onBlur={(event) =>
            edit({ name: event.currentTarget.textContent ?? "" })
          }
        >
          {content.name}
        </div>
        <div className="resume-contact">
          {[content.headline, content.contact].filter(Boolean).join(" · ")}
        </div>
      </header>

      <div
        className="resume-section"
        style={{ color: template.color, marginBottom: 6 }}
      >
        Summary
      </div>
      <p
        style={{ fontSize: 14, lineHeight: 1.65, margin: "0 0 22px" }}
        contentEditable
        suppressContentEditableWarning
        aria-label="Summary"
        onBlur={(event) =>
          edit({ summary: event.currentTarget.textContent ?? "" })
        }
      >
        {content.summary}
      </p>

      <div
        className="resume-section"
        style={{ color: template.color, marginBottom: 10 }}
      >
        Experience
      </div>
      {content.experience.map((position, p) => (
        <div key={`${position.title}-${p}`} style={{ marginBottom: 20 }}>
          <div className="row-between">
            <span className="resume-job-title">
              {position.title}
              {position.org ? ` — ${position.org}` : ""}
            </span>
            <span className="resume-when">{position.when}</span>
          </div>
          {position.bullets.map((bullet, b) => (
            <div key={b} className="resume-bullet">
              <span
                className="resume-bullet-dot"
                style={{ background: template.swatch }}
                aria-hidden="true"
              />
              <div style={{ flex: 1 }}>
                <span
                  className="resume-bullet-text"
                  data-rewritten={bullet.answers !== null}
                  contentEditable
                  suppressContentEditableWarning
                  onBlur={(event) =>
                    editBullet(p, b, event.currentTarget.textContent ?? "")
                  }
                >
                  {bullet.text}
                </span>
                <div className="resume-cite">{citeLine(bullet, evidence)}</div>
              </div>
            </div>
          ))}
        </div>
      ))}

      <div
        className="resume-section"
        style={{ color: template.color, marginBottom: 10 }}
      >
        Skills{reorder ? ", ordered for this role" : ""}
      </div>
      <div className="row" style={{ gap: 8 }}>
        {content.skills.map((skill, index) => (
          <span
            key={skill}
            className="resume-skill"
            data-lead={reorder && index < 3}
          >
            {skill}
          </span>
        ))}
      </div>

      <p
        style={{
          fontSize: 12,
          color: "#8a847e",
          marginTop: 24,
          marginBottom: 0,
        }}
      >
        Click any line to edit it directly. Grey notes show the source each line
        was written from.
      </p>
    </article>
  );
}

/** The grey note under a line: where it came from, and what it answers. */
export function citeLine(
  bullet: ResumeContent["experience"][number]["bullets"][number],
  evidence: TailoredResume["evidence"],
): string {
  const sources = bullet.evidence_ids
    .map((id) => evidence[id])
    .filter((note) => note !== undefined)
    .map((note) => note.reference);
  if (sources.length === 0) {
    return bullet.origin === "yours"
      ? "Your edit — no source cited"
      : "Source no longer in your profile";
  }
  const answers = bullet.answers ? ` — answers “${bullet.answers}”` : "";
  const edited = bullet.origin === "yours" ? " · edited by you" : "";
  return `${sources.join(" + ")}${answers}${edited}`;
}

function ChatPanel({
  model,
  target,
  enabled,
  exchanges,
  onSend,
  onApply,
  onDismiss,
}: {
  model: string;
  target: string | null;
  enabled: boolean;
  exchanges: Exchange[];
  onSend: (message: string) => void;
  onApply: (revisionId: string) => void;
  onDismiss: (index: number) => void;
}) {
  const [message, setMessage] = useState("");
  const streaming = exchanges.some((e) => e.streaming);
  const submit = (text: string) => {
    if (!text.trim() || streaming || !enabled) return;
    onSend(text.trim());
    setMessage("");
  };

  return (
    <div
      className="panel panel-tight"
      style={{ display: "flex", flexDirection: "column", minHeight: 420 }}
    >
      <div className="row" style={{ flexWrap: "nowrap" }}>
        <span className="ai-badge" aria-hidden="true">
          AI
        </span>
        <div>
          <div style={{ fontSize: 14.5, fontWeight: 700 }}>
            Revise with {model}
          </div>
          <div className="muted" style={{ fontSize: 12 }}>
            Writes from your sources to fit {target ?? "the role you pick"}
          </div>
        </div>
      </div>

      <div className="chat-log" aria-live="polite">
        <div className="bubble bubble-ai">
          {enabled
            ? `I have your profile and the bar for ${target ?? "this role"}. Ask me to rewrite anything — or use a suggestion below.`
            : "Write a résumé first; then ask me to rewrite anything in it."}
        </div>
        {exchanges.map((exchange, index) => (
          <div key={index} className="stack" style={{ gap: 10 }}>
            <div className="bubble bubble-mine">{exchange.request}</div>
            <div className="bubble bubble-ai">
              {exchange.reply || (exchange.streaming ? "…" : "")}
              {exchange.error && (
                <span
                  role="alert"
                  style={{
                    display: "block",
                    color: "var(--status-critical)",
                    fontWeight: 600,
                    marginTop: exchange.reply ? 8 : 0,
                  }}
                >
                  <span aria-hidden="true">⚠</span> {exchange.error}
                </span>
              )}
              {exchange.hasProposal &&
                exchange.revisionId &&
                !exchange.applied && (
                  <span className="row" style={{ marginTop: 10 }}>
                    <Button onClick={() => onApply(exchange.revisionId!)}>
                      Apply
                    </Button>
                    <Button variant="ghost" onClick={() => onDismiss(index)}>
                      Dismiss
                    </Button>
                  </span>
                )}
              {exchange.applied && (
                <span
                  className="muted"
                  style={{ display: "block", fontSize: 12, marginTop: 6 }}
                >
                  Applied as a new version.
                </span>
              )}
            </div>
          </div>
        ))}
      </div>

      <div className="row" style={{ gap: 6, marginBottom: 10 }}>
        {SUGGESTIONS.map((suggestion) => (
          <PillToggle
            key={suggestion}
            small
            pressed={false}
            disabled={!enabled || streaming}
            onClick={() => submit(suggestion)}
          >
            {suggestion}
          </PillToggle>
        ))}
      </div>
      <form
        className="row"
        style={{ flexWrap: "nowrap" }}
        onSubmit={(event) => {
          event.preventDefault();
          submit(message);
        }}
      >
        <input
          className="input"
          aria-label="Ask for a change"
          placeholder="Ask for a change…"
          value={message}
          disabled={!enabled}
          onChange={(event) => setMessage(event.target.value)}
        />
        <Button
          type="submit"
          disabled={!enabled || streaming || !message.trim()}
        >
          Send
        </Button>
      </form>
    </div>
  );
}

function WatchlistPanel({ onChanged }: { onChanged: () => void }) {
  const subscriptions = useAsync<Subscription[]>(
    () => api.get("/role-subscriptions"),
    [],
  );
  const [form, setForm] = useState({ role: "", company: "", url: "" });
  const [error, setError] = useState<string | null>(null);

  async function subscribe() {
    setError(null);
    try {
      await api.post("/role-subscriptions", {
        company_name: form.company.trim(),
        role_title: form.role.trim(),
        role_id: null,
        url: form.url.trim() || null,
      });
      setForm({ role: "", company: "", url: "" });
      await subscriptions.reload();
      onChanged();
    } catch (caught) {
      setError(messageOf(caught));
    }
  }

  async function remove(id: string) {
    setError(null);
    try {
      await api.del(`/role-subscriptions/${id}`);
      await subscriptions.reload();
      onChanged();
    } catch (caught) {
      setError(messageOf(caught));
    }
  }

  return (
    <div className="panel panel-tight">
      <Eyebrow style={{ marginBottom: 12 }}>Watchlist</Eyebrow>
      {(subscriptions.data ?? []).map((s) => (
        <div
          key={s.id}
          className="inset"
          style={{ padding: "9px 10px", marginBottom: 7 }}
        >
          <div className="row-between">
            <span
              className="ellipsis"
              style={{ fontSize: 13.5, fontWeight: 700 }}
            >
              {s.role_title || "Any role"} · {s.company_name}
            </span>
            <Button variant="ghost" onClick={() => void remove(s.id)}>
              Remove
            </Button>
          </div>
          <div className="ellipsis muted" style={{ fontSize: 12 }}>
            {s.url ? s.url.replace(/^https?:\/\//, "") : "No link saved"}
            {s.coverage === "manual"
              ? " · manual: paste its JD"
              : " · checked weekly"}
          </div>
        </div>
      ))}
      <div className="stack" style={{ gap: 8, marginTop: 8 }}>
        <input
          className="input"
          aria-label="Role to watch"
          placeholder="Role"
          value={form.role}
          onChange={(event) => setForm({ ...form, role: event.target.value })}
        />
        <input
          className="input"
          aria-label="Company to watch"
          placeholder="Company"
          value={form.company}
          onChange={(event) =>
            setForm({ ...form, company: event.target.value })
          }
        />
        <input
          className="input"
          aria-label="Careers or JD URL"
          placeholder="Careers or JD URL"
          value={form.url}
          onChange={(event) => setForm({ ...form, url: event.target.value })}
        />
        <div>
          <Button
            variant="secondary"
            disabled={!form.role.trim() || !form.company.trim()}
            onClick={() => void subscribe()}
          >
            Subscribe to this role
          </Button>
        </div>
      </div>
      <ErrorNote error={error} />
      <p className="subcopy" style={{ fontSize: 12.5, marginTop: 10 }}>
        Watched roles are checked weekly against the company&apos;s job board —
        found from the link you give — or, where there is no board we can read,
        rely on JDs you paste. They appear alongside your top matches in the gap
        plan and here.
      </p>
    </div>
  );
}
