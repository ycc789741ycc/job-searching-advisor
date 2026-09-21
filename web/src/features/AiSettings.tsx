import { useState } from "react";
import { api } from "../api/client";
import type { Budget, Credential } from "../api/types";
import {
  Button,
  ErrorNote,
  Field,
  Loading,
  StatTile,
  inputStyle,
} from "../components/ui";
import { messageOf, useAsync } from "./useAsync";

/**
 * The AI settings screen.
 *
 * The key is write-only: it is sent, and only ever read back as its last four
 * characters. Everything the app does with AI runs on it, so the budget lives
 * here too.
 */
export function AiSettings() {
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
      await credential.reload();
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
    <section>
      <h1>Your model</h1>
      <p className="secondary" style={{ maxWidth: 620 }}>
        Every analysis runs on your own provider and key. We store the key
        encrypted and never show it back to you — replace it any time.
      </p>

      <div className="card" style={{ maxWidth: 620, marginTop: 16 }}>
        {credential.loading ? (
          <Loading what="your settings" />
        ) : credential.data ? (
          <p className="secondary" style={{ marginTop: 0 }}>
            Currently using <strong>{credential.data.model}</strong> on{" "}
            {credential.data.provider}, key ending{" "}
            <code>····{credential.data.last_four}</code>.
            {credential.data.status === "failed" && (
              <span style={{ color: "var(--status-critical)" }}>
                {" "}
                ⚠ This key last failed: {credential.data.last_error}
              </span>
            )}
          </p>
        ) : (
          <p className="secondary" style={{ marginTop: 0 }}>
            No model configured yet. Analysis needs one.
          </p>
        )}

        <Field label="Provider">
          <select
            style={inputStyle}
            value={provider}
            onChange={(event) => {
              setProvider(event.target.value);
              const first = providers.data?.[event.target.value]?.[0];
              if (first) setModel(first);
            }}
          >
            {Object.keys(providers.data ?? { anthropic: [] }).map((name) => (
              <option key={name} value={name}>
                {name}
              </option>
            ))}
          </select>
        </Field>

        <Field
          label="Model"
          hint="Any model your provider serves. The listed ones are the ones we can price exactly."
        >
          <input
            style={inputStyle}
            value={model}
            list="model-suggestions"
            onChange={(event) => setModel(event.target.value)}
          />
          <datalist id="model-suggestions">
            {models.map((name) => (
              <option key={name} value={name} />
            ))}
          </datalist>
        </Field>

        <Field
          label="API key"
          hint="Stored encrypted. We only ever show the last four characters."
        >
          <input
            style={inputStyle}
            type="password"
            value={apiKey}
            autoComplete="off"
            placeholder={credential.data ? "Enter a new key to replace" : ""}
            onChange={(event) => setApiKey(event.target.value)}
          />
        </Field>

        {provider === "local" && (
          <Field
            label="Base URL"
            hint="A public URL you control. A model on your own laptop is not reachable from here."
          >
            <input
              style={inputStyle}
              value={baseUrl}
              placeholder="https://llm.example.com/v1"
              onChange={(event) => setBaseUrl(event.target.value)}
            />
          </Field>
        )}

        <ErrorNote error={saveError} />
        {saved && (
          <p style={{ color: "var(--status-good)", fontSize: 13.5 }}>
            <span aria-hidden="true">✓</span> Saved.
          </p>
        )}
        <Button onClick={save} busy={saving} disabled={!apiKey.trim()}>
          Save key
        </Button>
      </div>

      <h2 style={{ marginTop: 28 }}>Monthly budget</h2>
      <p className="secondary" style={{ maxWidth: 620 }}>
        Background work spends your money, so it stops at this cap and tells you
        rather than running past it.
      </p>
      <ErrorNote error={budget.error} />
      {budget.data && (
        <div
          style={{ display: "flex", gap: 12, flexWrap: "wrap", marginTop: 12 }}
        >
          <StatTile label="Cap" value={`$${budget.data.monthly_cap_usd}`} />
          <StatTile
            label="Spent this month"
            value={`$${budget.data.spent_this_month_usd}`}
          />
          <StatTile label="Remaining" value={`$${budget.data.remaining_usd}`} />
        </div>
      )}
      <div
        style={{
          display: "flex",
          gap: 8,
          alignItems: "flex-end",
          marginTop: 14,
          maxWidth: 360,
        }}
      >
        <div style={{ flex: 1 }}>
          <Field label="New monthly cap (USD)">
            <input
              style={inputStyle}
              inputMode="decimal"
              value={cap}
              onChange={(event) => setCap(event.target.value)}
            />
          </Field>
        </div>
        <div style={{ paddingBottom: 14 }}>
          <Button variant="secondary" onClick={saveCap} disabled={!cap.trim()}>
            Update
          </Button>
        </div>
      </div>
    </section>
  );
}
