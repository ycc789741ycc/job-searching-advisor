import { useMemo, useState } from "react";
import { api } from "../api/client";
import type {
  Assessment,
  CostEstimate,
  Fit,
  MatchedPosting,
  Role,
  RoleMapSettings,
  SalaryBand,
  Subscription,
} from "../api/types";
import { RoleMap, type RoleBubble } from "../charts/RoleMap";
import {
  AutoGrid,
  Button,
  Done,
  EmptyState,
  ErrorNote,
  Eyebrow,
  FitBadge,
  Loading,
  PillToggle,
  StatTile,
} from "../components/ui";
import { useShell } from "../shell/ShellContext";
import { useToast } from "../shell/toast";
import { CostConfirm } from "./CostConfirm";
import { messageOf, useAsync } from "./useAsync";

// The bound the api enforces on k (ADR 0003). The api is the authority; these
// only keep the input from offering a value it would refuse.
const MIN_ROLE_COUNT = 3;
const MAX_ROLE_COUNT = 20;

/** The role map: which roles exist in this user's market, and how they fit. */
export function Roles() {
  const flash = useToast();
  const { navigate } = useShell();
  const roles = useAsync<Role[]>(() => api.get("/roles"), []);
  const settings = useAsync<RoleMapSettings>(
    () => api.get("/roles/settings"),
    [],
  );
  const fits = useAsync<Fit[]>(() => api.get("/fits"), []);
  const assessment = useAsync<Assessment | null>(
    () => api.get("/assessments/latest"),
    [],
  );
  const subscriptions = useAsync<Subscription[]>(
    () => api.get("/role-subscriptions"),
    [],
  );
  const markets = useAsync<string[]>(() => api.get("/market-preferences"), []);
  const matched = useAsync<MatchedPosting[]>(
    () => api.get("/matched-postings?limit=10"),
    [],
  );

  const [company, setCompany] = useState("");
  const [watchRole, setWatchRole] = useState("");
  const [watchUrl, setWatchUrl] = useState("");
  const [market, setMarket] = useState("");
  const [bandMarket, setBandMarket] = useState<string | null>(null);
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
  const dimensionNames = useMemo(
    () =>
      new Map((assessment.data?.dimensions ?? []).map((d) => [d.key, d.name])),
    [assessment.data],
  );

  const bubbles: RoleBubble[] = (roles.data ?? []).map((role) => {
    const band = pickBand(role.salary_bands, bandMarket);
    const fit = fitByRole.get(role.id);
    return {
      id: role.id,
      name: role.name,
      hiringBar: role.hiring_bar,
      barBasis: role.bar_basis,
      salaryMid: band?.mid ?? null,
      salaryLabel: band ? bandLabel(band) : null,
      openings: role.opening_count,
      fit: fit?.score ?? null,
      reasoning: fit?.reasoning ?? role.bar_reasoning,
    };
  });

  // With nothing picked, the role that fits best is the one worth reading.
  const bestId = [...bubbles].sort((a, b) => (b.fit ?? -1) - (a.fit ?? -1))[0]
    ?.id;
  const activeId = selected ?? bestId;
  const activeRole = (roles.data ?? []).find((role) => role.id === activeId);
  const activeFit = activeId ? fitByRole.get(activeId) : undefined;
  const activeBand = activeRole
    ? pickBand(activeRole.salary_bands, bandMarket)
    : null;
  const postings = (roles.data ?? []).reduce(
    (sum, role) => sum + role.opening_count,
    0,
  );

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

  async function askForEstimate() {
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
  }

  return (
    <section>
      <ErrorNote error={error} />
      {queued && <Done>{queued}.</Done>}
      {estimate && (
        <CostConfirm
          busy={busy}
          onCancel={() => setEstimate(null)}
          onConfirm={() =>
            act("Role map queued", async () => {
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
          Your map covers up to {estimate.max_clusters ?? 0} of the{" "}
          {estimate.role_count ?? chosenRoleCount} roles closest to your
          profile. Naming them will cost at most{" "}
          <strong>${estimate.cost_usd}</strong> on {estimate.model_id} — usually
          less, since postings may form fewer roles than that, and roles already
          analysed are not paid for again. Grouping itself runs on our machines;
          your key pays only for naming the roles and reading out what they
          require.
        </CostConfirm>
      )}

      {roles.loading ? (
        <Loading what="your roles" />
      ) : bubbles.length === 0 ? (
        <EmptyState title="No roles yet">
          Add a market or watch a role below, then build your role map.
        </EmptyState>
      ) : (
        <AutoGrid col={400} gap={20}>
          <div className="panel">
            <div
              className="row-between"
              style={{
                alignItems: "flex-end",
                flexWrap: "wrap",
                marginBottom: 12,
              }}
            >
              <div>
                <h3 style={{ margin: 0 }}>Role market map</h3>
                <div className="subcopy">
                  Bubble size = fit. {postings.toLocaleString()} open postings
                  across {bubbles.length} roles.
                </div>
              </div>
              {(markets.data ?? []).length > 0 && (
                <div className="row" style={{ gap: 7 }}>
                  <PillToggle
                    small
                    pressed={bandMarket === null}
                    onClick={() => setBandMarket(null)}
                  >
                    Best sample
                  </PillToggle>
                  {(markets.data ?? []).map((name) => (
                    <PillToggle
                      key={name}
                      small
                      pressed={bandMarket === name}
                      onClick={() => setBandMarket(name)}
                    >
                      {name}
                    </PillToggle>
                  ))}
                </div>
              )}
            </div>
            <RoleMap
              roles={bubbles}
              selectedId={activeId}
              onSelect={setSelected}
            />
          </div>

          {activeRole && (
            <div className="panel panel-column">
              <Eyebrow>Selected role</Eyebrow>
              <h3 style={{ fontSize: 27, margin: "8px 0 6px" }}>
                {activeRole.name}
              </h3>
              <AutoGrid col={110} gap={10} style={{ margin: "10px 0 16px" }}>
                <StatTile
                  label="Fit"
                  value={activeFit ? `${activeFit.score}%` : "—"}
                />
                <StatTile
                  label="Band"
                  value={activeBand ? bandShort(activeBand) : "—"}
                />
                <StatTile
                  label="Openings"
                  value={String(activeRole.opening_count)}
                />
              </AutoGrid>
              <p style={{ fontSize: 14.5, lineHeight: 1.65 }}>
                {activeFit?.reasoning ??
                  activeRole.bar_reasoning ??
                  "Not scored yet — run an analysis, then re-score fit."}
              </p>

              {activeFit && activeFit.gaps.length > 0 && (
                <>
                  <Eyebrow style={{ margin: "6px 0" }}>
                    Where you clear it / where you don&apos;t
                  </Eyebrow>
                  {[...activeFit.gaps]
                    .sort((a, b) => a.delta - b.delta)
                    .map((gap) => {
                      const color =
                        gap.delta >= 0
                          ? "var(--color-accent-2-700)"
                          : "var(--color-accent-700)";
                      return (
                        <div
                          key={gap.dimension_key}
                          className="row"
                          style={{
                            gap: 11,
                            flexWrap: "nowrap",
                            padding: "8px 0",
                            borderBottom:
                              "1px solid color-mix(in srgb, #201e1d 10%, transparent)",
                          }}
                        >
                          <span
                            className="dot"
                            style={{ background: color }}
                            aria-hidden="true"
                          />
                          <span style={{ fontSize: 13.5, flex: 1 }}>
                            {dimensionNames.get(gap.dimension_key) ??
                              gap.dimension_key}
                          </span>
                          <span
                            style={{ fontSize: 12.5, fontWeight: 700, color }}
                          >
                            {gap.delta >= 0 ? `+${gap.delta}` : gap.delta}
                          </span>
                        </div>
                      );
                    })}
                </>
              )}

              {activeFit && activeFit.uncovered.length > 0 && (
                <>
                  <Eyebrow style={{ margin: "16px 0 6px" }}>
                    No evidence at all for these
                  </Eyebrow>
                  <p className="subcopy" style={{ marginBottom: 6 }}>
                    Different from a low score: nothing in your profile speaks
                    to them either way.
                  </p>
                  <ul style={{ fontSize: 13.5, margin: 0, paddingLeft: 18 }}>
                    {activeFit.uncovered.map((item) => (
                      <li key={item.statement}>{item.statement}</li>
                    ))}
                  </ul>
                </>
              )}

              <div className="panel-actions">
                <Button
                  onClick={() => navigate("plan", { roleId: activeRole.id })}
                >
                  Draft the plan with AI
                </Button>
                <Button
                  variant="secondary"
                  onClick={() => navigate("resume", { roleId: activeRole.id })}
                >
                  Tailor résumé
                </Button>
              </div>

              <details style={{ marginTop: 16 }}>
                <summary
                  className="eyebrow"
                  style={{ cursor: "pointer", display: "list-item" }}
                >
                  What this role asks for
                </summary>
                <ul
                  style={{ fontSize: 13.5, margin: "8px 0 0", paddingLeft: 18 }}
                >
                  {activeRole.requirements.map((requirement) => (
                    <li key={requirement.statement}>
                      {requirement.statement}{" "}
                      <span className="muted">
                        ({requirement.expected_level})
                      </span>
                    </li>
                  ))}
                </ul>
              </details>
            </div>
          )}
        </AutoGrid>
      )}

      {(matched.data ?? []).length > 0 && (
        <div className="panel" style={{ marginTop: 20 }}>
          <h3>Top matched openings</h3>
          <p className="subcopy">
            Open postings inside your roles, ranked by how well you fit the
            role. A posting&apos;s own requirements do not change its rank yet.
          </p>
          <div className="stack" style={{ gap: 8, marginTop: 12 }}>
            {(matched.data ?? []).map((match, index) => (
              <div
                key={match.posting_id}
                className="row"
                style={{
                  gap: 14,
                  flexWrap: "nowrap",
                  padding: "11px 14px",
                  borderRadius: 999,
                  background: "var(--color-bg)",
                }}
              >
                <span
                  style={{
                    fontFamily: "var(--font-heading)",
                    fontSize: 13,
                    width: 26,
                    color: "var(--color-neutral-700)",
                  }}
                >
                  {String(index + 1).padStart(2, "0")}
                </span>
                <FitBadge fit={match.fit} />
                <div style={{ flex: 1, minWidth: 0 }}>
                  <div
                    style={{
                      fontSize: 14,
                      fontWeight: 700,
                      overflow: "hidden",
                      textOverflow: "ellipsis",
                      whiteSpace: "nowrap",
                    }}
                  >
                    {match.role_name} · {match.company_name}
                  </div>
                  <div
                    className="subcopy"
                    style={{
                      fontSize: 12.5,
                      overflow: "hidden",
                      textOverflow: "ellipsis",
                      whiteSpace: "nowrap",
                    }}
                  >
                    {match.salary
                      ? `${match.salary.currency} ${Math.round(match.salary.min / 1000)}k–${Math.round(match.salary.max / 1000)}k · `
                      : ""}
                    {match.url ? (
                      <a href={match.url} rel="noreferrer" target="_blank">
                        {match.title}
                      </a>
                    ) : (
                      match.title
                    )}
                    {match.location ? ` · ${match.location}` : ""}
                  </div>
                </div>
                <PillToggle
                  small
                  pressed={match.subscription_id !== null}
                  disabled={busy}
                  onClick={() =>
                    void act(
                      match.subscription_id
                        ? "Removed from your watchlist"
                        : "Added to your watchlist",
                      async () => {
                        if (match.subscription_id) {
                          await api.del(
                            `/role-subscriptions/${match.subscription_id}`,
                          );
                        } else {
                          await api.post("/role-subscriptions", {
                            company_name: match.company_name,
                            role_title: match.role_name,
                            role_id: match.role_id,
                            url: match.url,
                          });
                          flash(
                            `Subscribed to ${match.role_name} at ${match.company_name}.`,
                          );
                        }
                        await Promise.all([
                          subscriptions.reload(),
                          matched.reload(),
                        ]);
                      },
                    )
                  }
                >
                  {match.subscription_id ? "Subscribed" : "Subscribe"}
                </PillToggle>
              </div>
            ))}
          </div>
        </div>
      )}

      <AutoGrid col={300} gap={20} style={{ marginTop: 20 }}>
        <div className="panel">
          <h3>Markets you are looking in</h3>
          <p className="subcopy">
            Postings in these markets feed your map, and their salary bands are
            what the pills above switch between.
          </p>
          <div className="row" style={{ flexWrap: "nowrap", marginTop: 10 }}>
            <input
              className="input"
              aria-label="Market"
              value={market}
              placeholder="Berlin, Remote EU…"
              onChange={(event) => setMarket(event.target.value)}
            />
            <Button
              variant="secondary"
              disabled={!market.trim()}
              onClick={() =>
                act("Market added", async () => {
                  await api.post("/market-preferences", { market });
                  setMarket("");
                  await markets.reload();
                })
              }
            >
              Add
            </Button>
          </div>
          <p className="muted" style={{ fontSize: 12.5, margin: "8px 0 0" }}>
            {(markets.data ?? []).join(" · ") || "None selected yet"}
          </p>
        </div>

        <div className="panel">
          <h3>Roles to watch</h3>
          <p className="subcopy">
            A role at a company, with its careers or JD link if you have one.
            Watched roles are checked weekly and appear in your gap plan and
            résumé targets.
          </p>
          <div className="stack" style={{ gap: 8, marginTop: 10 }}>
            <input
              className="input"
              aria-label="Role"
              list="watch-role-options"
              value={watchRole}
              placeholder="Senior Backend Engineer"
              onChange={(event) => setWatchRole(event.target.value)}
            />
            <datalist id="watch-role-options">
              {(roles.data ?? []).map((role) => (
                <option key={role.id} value={role.name} />
              ))}
            </datalist>
            <input
              className="input"
              aria-label="Company"
              value={company}
              placeholder="Company"
              onChange={(event) => setCompany(event.target.value)}
            />
            <input
              className="input"
              aria-label="Careers or JD link"
              type="url"
              value={watchUrl}
              placeholder="Careers or JD URL (optional)"
              onChange={(event) => setWatchUrl(event.target.value)}
            />
            <div>
              <Button
                variant="secondary"
                disabled={!company.trim() || !watchRole.trim()}
                onClick={() =>
                  act("Role added to your watchlist", async () => {
                    const known = (roles.data ?? []).find(
                      (role) => role.name === watchRole.trim(),
                    );
                    await api.post("/role-subscriptions", {
                      company_name: company,
                      role_title: watchRole,
                      role_id: known?.id ?? null,
                      url: watchUrl.trim() || null,
                    });
                    flash(`Subscribed to ${watchRole} at ${company}.`);
                    setCompany("");
                    setWatchRole("");
                    setWatchUrl("");
                    await subscriptions.reload();
                  })
                }
              >
                Subscribe to this role
              </Button>
            </div>
          </div>
          {(subscriptions.data ?? []).length > 0 && (
            <div className="stack" style={{ gap: 7, marginTop: 14 }}>
              {(subscriptions.data ?? []).map((subscription) => (
                <div
                  key={subscription.id}
                  className="inset"
                  style={{ padding: "9px 12px" }}
                >
                  <div className="row-between">
                    <span style={{ fontSize: 13.5, fontWeight: 700 }}>
                      {subscription.role_title || "Any role"} ·{" "}
                      {subscription.company_name}
                    </span>
                    <Button
                      variant="ghost"
                      onClick={() =>
                        act("Removed from your watchlist", async () => {
                          await api.del(
                            `/role-subscriptions/${subscription.id}`,
                          );
                          await subscriptions.reload();
                        })
                      }
                    >
                      Remove
                    </Button>
                  </div>
                  <div
                    className="subcopy"
                    style={{
                      fontSize: 12,
                      overflow: "hidden",
                      textOverflow: "ellipsis",
                      whiteSpace: "nowrap",
                    }}
                  >
                    {subscription.url ? (
                      <a
                        href={subscription.url}
                        rel="noreferrer"
                        target="_blank"
                      >
                        {subscription.url.replace(/^https?:\/\//, "")}
                      </a>
                    ) : (
                      "No link saved"
                    )}
                    {subscription.coverage === "manual"
                      ? " · no job board we can read — paste a JD instead"
                      : " · checked weekly"}
                  </div>
                </div>
              ))}
            </div>
          )}
        </div>

        <div className="panel">
          <h3>Roles to analyse</h3>
          <p className="subcopy">
            How many of the roles closest to your profile the map analyses —
            each one costs calls on your key.
          </p>
          <label className="field-label" htmlFor="role-count-input">
            Roles ({MIN_ROLE_COUNT}–{MAX_ROLE_COUNT})
          </label>
          <input
            id="role-count-input"
            className="input"
            type="number"
            min={MIN_ROLE_COUNT}
            max={MAX_ROLE_COUNT}
            style={{ maxWidth: 140 }}
            value={chosenRoleCount ?? ""}
            onChange={(event) => {
              setRoleCount(Number(event.target.value));
              setEstimate(null);
            }}
          />
          <div className="row" style={{ marginTop: 14 }}>
            <Button busy={busy} onClick={askForEstimate}>
              Build role map
            </Button>
            <Button
              variant="secondary"
              busy={busy}
              onClick={() =>
                act("Fits queued", () => api.post("/fits/compute"))
              }
            >
              Re-score fit
            </Button>
          </div>
        </div>
      </AutoGrid>
    </section>
  );
}

/**
 * The band for one market, or the best-sampled one. A thin band is still
 * shown, just flagged. Pure.
 */
export function pickBand(
  bands: Record<string, SalaryBand>,
  market: string | null = null,
): SalaryBand | null {
  if (market !== null) return bands?.[market] ?? null;
  const entries = Object.values(bands ?? {});
  if (entries.length === 0) return null;
  return entries.find((band) => band.is_confident) ?? entries[0] ?? null;
}

function bandShort(band: SalaryBand): string {
  return `${Math.round(band.low / 1000)}–${Math.round(band.high / 1000)}k`;
}

function bandLabel(band: SalaryBand): string {
  return `${band.currency} ${bandShort(band)}${band.is_confident ? "" : " (thin sample)"}`;
}
