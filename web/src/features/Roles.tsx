import { useMemo, useState } from "react";
import { api } from "../api/client";
import type {
  CostEstimate,
  Fit,
  Role,
  RoleMapSettings,
  SalaryBand,
  Subscription,
} from "../api/types";
import { RoleMap, type RoleBubble } from "../charts/RoleMap";
import {
  Button,
  EmptyState,
  ErrorNote,
  Loading,
  inputStyle,
} from "../components/ui";
import { messageOf, useAsync } from "./useAsync";

// The bound the api enforces on k (ADR 0003). The api is the authority; these
// only keep the input from offering a value it would refuse.
const MIN_ROLE_COUNT = 3;
const MAX_ROLE_COUNT = 20;

/** The role map: which roles exist in this user's market, and how they fit. */
export function Roles() {
  const roles = useAsync<Role[]>(() => api.get("/roles"), []);
  const settings = useAsync<RoleMapSettings>(
    () => api.get("/roles/settings"),
    [],
  );
  const fits = useAsync<Fit[]>(() => api.get("/fits"), []);
  const subscriptions = useAsync<Subscription[]>(
    () => api.get("/company-subscriptions"),
    [],
  );
  const markets = useAsync<string[]>(() => api.get("/market-preferences"), []);

  const [company, setCompany] = useState("");
  const [market, setMarket] = useState("");
  const [estimate, setEstimate] = useState<CostEstimate | null>(null);
  // The k being considered; saved only once its estimate is confirmed.
  const [roleCount, setRoleCount] = useState<number | null>(null);
  const savedRoleCount = settings.data?.role_count;
  const chosenRoleCount = roleCount ?? savedRoleCount;
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [queued, setQueued] = useState<string | null>(null);
  const [selected, setSelected] = useState<string | undefined>(undefined);

  const fitByRole = useMemo(
    () => new Map((fits.data ?? []).map((fit) => [fit.role_id, fit])),
    [fits.data],
  );

  const bubbles: RoleBubble[] = (roles.data ?? []).map((role) => {
    const band = pickBand(role.salary_bands);
    const fit = fitByRole.get(role.id);
    return {
      id: role.id,
      name: role.name,
      hiringBar: role.hiring_bar,
      barBasis: role.bar_basis,
      salaryMid: band?.mid ?? null,
      salaryLabel: band
        ? `${band.currency} ${Math.round(band.low / 1000)}k–${Math.round(band.high / 1000)}k${
            band.is_confident ? "" : " (thin sample)"
          }`
        : null,
      openings: role.opening_count,
      fit: fit?.score ?? null,
      reasoning: fit?.reasoning ?? role.bar_reasoning,
    };
  });

  const activeFit = selected ? fitByRole.get(selected) : undefined;
  const activeRole = (roles.data ?? []).find((role) => role.id === selected);

  async function act(label: string, run: () => Promise<unknown>) {
    setBusy(true);
    setError(null);
    try {
      await run();
      setQueued(label);
    } catch (caught) {
      setError(messageOf(caught));
    } finally {
      setBusy(false);
    }
  }

  return (
    <section>
      <h1>Your role map</h1>
      <p className="secondary" style={{ maxWidth: 680 }}>
        Roles are grouped from real openings in the markets and companies you
        chose, on your own model. Nothing is scraped from sites that forbid it.
      </p>

      <div className="card" style={{ marginTop: 12 }}>
        <div
          style={{
            display: "flex",
            gap: 16,
            flexWrap: "wrap",
            alignItems: "flex-end",
          }}
        >
          <div style={{ flex: "1 1 220px" }}>
            <label
              style={{ fontSize: 13.5, fontWeight: 600 }}
              htmlFor="market-input"
            >
              Markets you are looking in
            </label>
            <div style={{ display: "flex", gap: 8, marginTop: 4 }}>
              <input
                id="market-input"
                style={inputStyle}
                value={market}
                placeholder="Berlin, Remote EU…"
                onChange={(event) => setMarket(event.target.value)}
              />
              <Button
                variant="secondary"
                disabled={!market.trim()}
                onClick={() =>
                  act("market added", async () => {
                    await api.post("/market-preferences", { market });
                    setMarket("");
                    await markets.reload();
                  })
                }
              >
                Add
              </Button>
            </div>
            <p className="muted" style={{ fontSize: 12.5, margin: "6px 0 0" }}>
              {(markets.data ?? []).join(" · ") || "None selected yet"}
            </p>
          </div>

          <div style={{ flex: "1 1 220px" }}>
            <label
              style={{ fontSize: 13.5, fontWeight: 600 }}
              htmlFor="company-input"
            >
              Companies to watch
            </label>
            <div style={{ display: "flex", gap: 8, marginTop: 4 }}>
              <input
                id="company-input"
                style={inputStyle}
                value={company}
                placeholder="Northwind Pay"
                onChange={(event) => setCompany(event.target.value)}
              />
              <Button
                variant="secondary"
                disabled={!company.trim()}
                onClick={() =>
                  act("company added", async () => {
                    await api.post("/company-subscriptions", {
                      company_name: company,
                    });
                    setCompany("");
                    await subscriptions.reload();
                  })
                }
              >
                Watch
              </Button>
            </div>
            <ul
              className="muted"
              style={{ fontSize: 12.5, margin: "6px 0 0", paddingLeft: 16 }}
            >
              {(subscriptions.data ?? []).map((subscription) => (
                <li key={subscription.company_id}>
                  {subscription.company_name}
                  {subscription.coverage === "manual" && (
                    <> — no job board we can read; paste a JD instead</>
                  )}
                </li>
              ))}
            </ul>
          </div>

          <div style={{ flex: "0 1 150px" }}>
            <label
              style={{ fontSize: 13.5, fontWeight: 600 }}
              htmlFor="role-count-input"
            >
              Roles to analyse
            </label>
            <input
              id="role-count-input"
              type="number"
              min={MIN_ROLE_COUNT}
              max={MAX_ROLE_COUNT}
              style={{ ...inputStyle, marginTop: 4 }}
              value={chosenRoleCount ?? ""}
              onChange={(event) => {
                setRoleCount(Number(event.target.value));
                setEstimate(null);
              }}
            />
            <p className="muted" style={{ fontSize: 12.5, margin: "6px 0 0" }}>
              {MIN_ROLE_COUNT}–{MAX_ROLE_COUNT}; more roles cost more
            </p>
          </div>

          <div style={{ display: "flex", gap: 8 }}>
            <Button
              busy={busy}
              onClick={async () => {
                setBusy(true);
                setError(null);
                try {
                  setEstimate(
                    await api.get<CostEstimate>(
                      chosenRoleCount === undefined
                        ? "/roles/cost-estimate"
                        : `/roles/cost-estimate?role_count=${chosenRoleCount}`,
                    ),
                  );
                } catch (caught) {
                  setError(messageOf(caught));
                } finally {
                  setBusy(false);
                }
              }}
            >
              Build role map
            </Button>
            <Button
              variant="secondary"
              busy={busy}
              onClick={() =>
                act("fits queued", () => api.post("/fits/compute"))
              }
            >
              Re-score fit
            </Button>
          </div>
        </div>
      </div>

      <ErrorNote error={error} />
      {queued && (
        <p style={{ color: "var(--status-good)", fontSize: 13.5 }}>
          <span aria-hidden="true">✓</span> {queued}.
        </p>
      )}

      {estimate && (
        <div className="card" style={{ maxWidth: 620, marginTop: 12 }}>
          <h3 style={{ marginTop: 0 }}>Before we spend anything</h3>
          <p className="secondary" style={{ fontSize: 14 }}>
            Your map covers up to {estimate.max_clusters ?? 0} of the{" "}
            {estimate.role_count ?? chosenRoleCount} roles closest to your
            profile. Naming them will cost at most{" "}
            <strong>${estimate.cost_usd}</strong> on {estimate.model_id} —
            usually less, since postings may form fewer roles than that, and
            roles already analysed are not paid for again. Grouping itself runs
            on our machines; your key pays only for naming the roles and reading
            out what they require.
          </p>
          <div style={{ display: "flex", gap: 8 }}>
            <Button
              busy={busy}
              onClick={() =>
                act("role map queued", async () => {
                  if (
                    chosenRoleCount !== undefined &&
                    chosenRoleCount !== savedRoleCount
                  ) {
                    // Saving a new k queues the rebuild itself.
                    await api.put("/roles/settings", {
                      role_count: chosenRoleCount,
                    });
                    await settings.reload();
                    setRoleCount(null);
                  } else {
                    await api.post("/roles/recluster");
                  }
                  setEstimate(null);
                })
              }
            >
              Run it
            </Button>
            <Button variant="secondary" onClick={() => setEstimate(null)}>
              Cancel
            </Button>
          </div>
        </div>
      )}

      {roles.loading ? (
        <Loading what="your roles" />
      ) : bubbles.length === 0 ? (
        <EmptyState title="No roles yet">
          Add a market or watch a company, then build your role map.
        </EmptyState>
      ) : (
        <div className="card" style={{ marginTop: 16 }}>
          <RoleMap
            roles={bubbles}
            selectedId={selected}
            onSelect={setSelected}
          />
        </div>
      )}

      {activeRole && (
        <div className="card" style={{ marginTop: 16 }}>
          <h2 style={{ marginTop: 0 }}>{activeRole.name}</h2>
          {activeFit ? (
            <>
              <p className="secondary" style={{ fontSize: 14 }}>
                Fit {activeFit.score}/100. {activeFit.reasoning}
              </p>
              {activeFit.gaps.filter((gap) => gap.delta < 0).length > 0 && (
                <>
                  <h3 style={{ fontSize: 14 }}>Where you are short</h3>
                  <table className="data-table" style={{ maxWidth: 520 }}>
                    <thead>
                      <tr>
                        <th>Dimension</th>
                        <th>You</th>
                        <th>Expected</th>
                        <th>Gap</th>
                      </tr>
                    </thead>
                    <tbody>
                      {activeFit.gaps
                        .filter((gap) => gap.delta < 0)
                        .sort((a, b) => a.delta - b.delta)
                        .map((gap) => (
                          <tr key={gap.dimension_key}>
                            <td>{gap.dimension_key}</td>
                            <td>{gap.user_score}</td>
                            <td>{gap.target_score}</td>
                            <td style={{ color: "var(--status-critical)" }}>
                              {gap.delta}
                            </td>
                          </tr>
                        ))}
                    </tbody>
                  </table>
                </>
              )}
              {activeFit.uncovered.length > 0 && (
                <>
                  <h3 style={{ fontSize: 14, marginTop: 16 }}>
                    No evidence at all for these
                  </h3>
                  <p className="muted" style={{ fontSize: 13 }}>
                    These are different from a low score: nothing in your
                    profile speaks to them either way.
                  </p>
                  <ul style={{ fontSize: 13.5 }}>
                    {activeFit.uncovered.map((item) => (
                      <li key={item.statement}>{item.statement}</li>
                    ))}
                  </ul>
                </>
              )}
            </>
          ) : (
            <p className="muted" style={{ fontSize: 13.5 }}>
              Not scored yet — run an analysis, then re-score fit.
            </p>
          )}
          <h3 style={{ fontSize: 14, marginTop: 16 }}>
            What this role asks for
          </h3>
          <ul style={{ fontSize: 13.5 }}>
            {activeRole.requirements.map((requirement) => (
              <li key={requirement.statement}>
                {requirement.statement}{" "}
                <span className="muted">({requirement.expected_level})</span>
              </li>
            ))}
          </ul>
        </div>
      )}
    </section>
  );
}

function pickBand(bands: Record<string, SalaryBand>): SalaryBand | null {
  const entries = Object.values(bands ?? {});
  if (entries.length === 0) return null;
  // Prefer a well-sampled band; a thin one is still shown, just flagged.
  return entries.find((band) => band.is_confident) ?? entries[0] ?? null;
}
