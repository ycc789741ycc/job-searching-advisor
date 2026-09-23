import { useState } from "react";
import { api } from "../api/client";
import type { Budget, Credential } from "../api/types";
import {
  AutoGrid,
  Button,
  Done,
  ErrorNote,
  Eyebrow,
  Field,
  Loading,
  PillToggle,
  StatTile,
} from "../components/ui";
import { useShell } from "../shell/ShellContext";
import { messageOf, useAsync } from "./useAsync";

const USES = [
  {
    title: "Follow-up questions",
    note: "Written when the evidence leaves a score uncertain.",
  },
  {
    title: "Skill analysis",
    note: "Reads your evidence into your own dimensions, citing each fact.",
  },
  {
    title: "Role map",
    note: "Names the roles grouped from real postings and reads out what they require.",
  },
  {
    title: "Gap plan and résumé",
    note: "Drafts milestones for a role you pick, and writes a résumé from cited work.",
  },
];

/**
 * The AI settings screen.
 *
 * The key is write-only: it is sent, and only ever read back as its last four
 * characters. Everything the app does with AI runs on it, so the budget lives
 * here too.
 */
export function AiSettings() {
  const { refresh } = useShell();
  const credential = useAsync<Credential | null>(
    () => api.get("/ai-credential"),
    [],
  );
  const budget = useAsync<Budget>(() => api.get("/ai-budget"), []);
  const providers = useAsync<Record<string, string[]>>(
    () => api.get("/ai-providers"),
    [],
  );

  const [provider, setProvider] = useState("anthropic");
  const [model, setModel] = useState("claude-opus-5");
  const [apiKey, setApiKey] = useState("");
  const [baseUrl, setBaseUrl] = useState("");
  const [cap, setCap] = useState("");
  const [saving, setSaving] = useState(false);
  const [saveError, setSaveError] = useState<string | null>(null);
  const [saved, setSaved] = useState(false);

  const models = providers.data?.[provider] ?? [];

  async function save() {
    setSaving(true);
    setSaveError(null);
    setSaved(false);
    try {
      await api.put("/ai-credential", {
        provider,
        model,
        api_key: apiKey,
        base_url: baseUrl || null,
      });
      setApiKey("");
      setSaved(true);
      await Promise.all([credential.reload(), refresh()]);
    } catch (caught) {
      setSaveError(messageOf(caught));
    } finally {
      setSaving(false);
    }
  }

  async function saveCap() {
    try {
      await api.put("/ai-budget", { monthly_cap_usd: cap });
      setCap("");
      await budget.reload();
    } catch (caught) {
      budget.setError(messageOf(caught));
    }
  }

  return (
    <AutoGrid col={340}>
      <div className="panel">
        <h3>Your model, your key</h3>
        <p className="subcopy" style={{ fontSize: 14, lineHeight: 1.65 }}>
          Nothing here ships a model of its own. Point it at a provider you
          already pay for — the key is stored encrypted on the server and never
          shown back to you.
        </p>

        {credential.loading ? (
          <Loading what="your settings" />
        ) : credential.data ? (
          <p className="model-pill" style={{ margin: "4px 0 16px" }}>
            Using {credential.data.model} on {credential.data.provider} · key
            ending ····{credential.data.last_four}
          </p>
        ) : (
          <p className="model-pill" style={{ margin: "4px 0 16px" }}>
            No model configured yet — analysis needs one.
          </p>
        )}
        {credential.data?.status === "failed" && (
          <ErrorNote
            error={`This key last failed: ${credential.data.last_error}`}
          />
        )}

        <div style={{ marginBottom: 14 }}>
          <span className="field-label" id="provider-label">
            Provider
          </span>
          <div
            className="row"
            style={{ gap: 8 }}
            role="group"
            aria-labelledby="provider-label"
          >
            {Object.keys(providers.data ?? { anthropic: [] }).map((name) => (
              <PillToggle
                key={name}
                pressed={provider === name}
                onClick={() => {
                  setProvider(name);
                  const first = providers.data?.[name]?.[0];
                  if (first) setModel(first);
                }}
              >
                {name}
              </PillToggle>
            ))}
          </div>
        </div>

        <Field
          label="Model"
          hint="Any model your provider serves. The listed ones are the ones we can price exactly."
        >
          <input
            className="input"
            value={model}
            list="model-suggestions"
            onChange={(event) => setModel(event.target.value)}
          />
        </Field>
        <datalist id="model-suggestions">
          {models.map((name) => (
            <option key={name} value={name} />
          ))}
        </datalist>

        <Field
          label="API key"
          hint="Stored encrypted. We only ever show the last four characters."
        >
          <input
            className="input"
            type="password"
            value={apiKey}
            autoComplete="off"
            placeholder={
              credential.data ? "Enter a new key to replace" : "sk-…"
            }
            onChange={(event) => setApiKey(event.target.value)}
          />
        </Field>

        {provider === "local" && (
          <Field
            label="Base URL"
            hint="A public URL you control. A model on your own laptop is not reachable from here."
          >
            <input
              className="input"
              value={baseUrl}
              placeholder="https://llm.example.com/v1"
              onChange={(event) => setBaseUrl(event.target.value)}
            />
          </Field>
        )}

        <ErrorNote error={saveError} />
        {saved && <Done>Saved.</Done>}
        <Button onClick={save} busy={saving} disabled={!apiKey.trim()}>
          Save key
        </Button>
      </div>

      <div className="stack" style={{ gap: 20 }}>
        <div className="callout">
          <Eyebrow style={{ marginBottom: 6 }}>
            Where this model is used
          </Eyebrow>
          <div className="divided">
            {USES.map((use) => (
              <div key={use.title}>
                <div style={{ fontSize: 14.5, fontWeight: 700 }}>
                  {use.title}
                </div>
                <div
                  className="callout-note"
                  style={{ fontSize: 13, lineHeight: 1.55, marginTop: 3 }}
                >
                  {use.note}
                </div>
              </div>
            ))}
          </div>
          <p
            className="callout-note"
            style={{ fontSize: 12.5, lineHeight: 1.55, margin: "14px 0 0" }}
          >
            Without a key, the app still charts what the connectors return — but
            no follow-up questions, gap plan or résumé revision is generated.
            Reading your sources never calls a model.
          </p>
        </div>

        <div className="panel">
          <h3>Monthly budget</h3>
          <p className="subcopy">
            Background work spends your money, so it stops at this cap and tells
            you rather than running past it.
          </p>
          <ErrorNote error={budget.error} />
          {budget.data && (
            <AutoGrid col={110} gap={10} style={{ margin: "12px 0 14px" }}>
              <StatTile label="Cap" value={`$${budget.data.monthly_cap_usd}`} />
              <StatTile
                label="Spent"
                value={`$${budget.data.spent_this_month_usd}`}
              />
              <StatTile
                label="Remaining"
                value={`$${budget.data.remaining_usd}`}
              />
            </AutoGrid>
          )}
          <div
            className="row"
            style={{ alignItems: "flex-end", flexWrap: "nowrap" }}
          >
            <div style={{ flex: 1 }}>
              <Field label="New monthly cap (USD)">
                <input
                  className="input"
                  inputMode="decimal"
                  value={cap}
                  onChange={(event) => setCap(event.target.value)}
                />
              </Field>
            </div>
            <div style={{ paddingBottom: 14 }}>
              <Button
                variant="secondary"
                onClick={saveCap}
                disabled={!cap.trim()}
              >
                Update
              </Button>
            </div>
          </div>
        </div>
      </div>
    </AutoGrid>
  );
}
