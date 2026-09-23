import "@testing-library/jest-dom/vitest";
import { render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import type { Plan, PlanSummary, TargetOption } from "../api/types";
import { ShellContext, type Shell } from "../shell/ShellContext";
import { ToastProvider } from "../shell/toast";
import { GapPlan } from "./GapPlan";
import { ago } from "./time";

const option: TargetOption = {
  kind: "matchedPosting",
  id: "p1",
  title: "Senior Backend Engineer",
  role_name: "Senior Backend Engineer",
  role_id: "r1",
  company_name: "Northwind Pay",
  label: "Senior Backend Engineer · Northwind Pay",
  fit: 71,
  salary: null,
  source_kind: "atsBoard",
  url: null,
  subscription_id: null,
};

const summary: PlanSummary = {
  id: "plan-1",
  target: { kind: "matchedPosting", id: "p1" },
  label: option.label,
  version: 1,
  status: "ready",
  error: null,
  model_id: "claude-opus-5",
  created_at: "2026-09-20T10:00:00Z",
  drafted_at: "2026-09-20T10:01:00Z",
  progress: 25,
};

const readyPlan: Plan = {
  ...summary,
  template_version: "gap_plan@v1",
  snapshot: {
    title: option.title,
    company: option.company_name,
    role_name: option.role_name,
    fit: 71,
    basis: "role",
    requirements: [],
    taken_at: "2026-09-20T10:00:00Z",
  },
  gaps: [
    {
      key: "req:org",
      kind: "uncovered",
      name: "Demonstrated org-level influence",
      user_score: null,
      target_score: null,
      lift: 25,
      why: "They ask for it; nothing shows it.",
      evidence: [],
    },
    {
      key: "dim:leadership",
      kind: "dimension",
      name: "Technical leadership",
      user_score: 70,
      target_score: 90,
      lift: 10,
      why: "They expect 90.",
      evidence: [
        { id: "e1", reference: "GitHub · payments-svc", fact: "38 merged PRs" },
      ],
    },
  ],
  milestones: [
    {
      id: "m1",
      title: "Own one cross-team outcome",
      window: "Weeks 1-6",
      outcome: "The artefact panels ask for.",
      tasks: [
        {
          id: "t1",
          text: "Lead the checkout migration",
          due: "Wk 1",
          closes: ["dim:leadership"],
          done: false,
          done_elsewhere: false,
        },
        {
          id: "t2",
          text: "Present at all-hands",
          due: "Wk 8",
          closes: ["req:org"],
          done: false,
          done_elsewhere: true,
        },
      ],
    },
  ],
  projects: [],
  stepping_stones: [
    { role_id: "r2", name: "Platform Engineer", fit: 84, openings: 9 },
  ],
  versions: [summary],
};

type Route = (method: string, url: string, body: unknown) => unknown;

function json(body: unknown, status = 200): Response {
  return new Response(body === undefined ? null : JSON.stringify(body), {
    status: body === undefined ? 204 : status,
    headers: { "Content-Type": "application/json" },
  });
}

function serve(route: Route) {
  const calls: { method: string; url: string; body: unknown }[] = [];
  vi.stubGlobal(
    "fetch",
    vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
      const url = String(input).replace("http://api.test/api/v1", "");
      const method = init?.method ?? "GET";
      const body = init?.body ? JSON.parse(String(init.body)) : undefined;
      calls.push({ method, url, body });
      return json(route(method, url, body));
    }),
  );
  return calls;
}

function renderPlan(overrides: Partial<Shell> = {}) {
  const shell: Shell = {
    status: {
      me: null,
      credential: {
        provider: "anthropic",
        model: "claude-opus-5",
        base_url: null,
        last_four: "abcd",
        status: "active",
        last_error: null,
      },
      openQuestions: 0,
      confidence: 80,
    },
    navigate: vi.fn(),
    handoff: null,
    refresh: async () => {},
    target: null,
    setTarget: vi.fn(),
    ...overrides,
  };
  render(
    <ShellContext.Provider value={shell}>
      <ToastProvider>
        <GapPlan />
      </ToastProvider>
    </ShellContext.Provider>,
  );
  return shell;
}

describe("gap plan screen", () => {
  beforeEach(() => {
    window.__APP_CONFIG__ = { apiBaseUrl: "http://api.test" };
  });
  afterEach(() => vi.unstubAllGlobals());

  it("prices a plan before anything is spent, then shows it drafting", async () => {
    const calls = serve((method, url) => {
      if (url === "/targets") return [option];
      if (url === "/gap-plans" && method === "GET") return [];
      if (url.startsWith("/gap-plans/cost-estimate"))
        return { cost_usd: "0.04", model_id: "claude-opus-5" };
      if (url === "/gap-plans" && method === "POST")
        return { ...summary, status: "drafting", progress: 0 };
      if (url === "/gap-plans/plan-1")
        return { ...readyPlan, status: "drafting", gaps: [], milestones: [] };
      return null;
    });
    const user = userEvent.setup();
    renderPlan();

    expect(await screen.findByText("No plan yet")).toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: "Generate gap plan" }));

    const confirm = await screen.findByRole("region", {
      name: "Cost estimate",
    });
    expect(confirm).toHaveTextContent("$0.04");
    expect(calls.some((c) => c.method === "POST")).toBe(false);

    await user.click(within(confirm).getByRole("button", { name: "Run it" }));
    expect(
      await screen.findByText(/Drafting on claude-opus-5/),
    ).toBeInTheDocument();
    expect(calls).toContainEqual({
      method: "POST",
      url: "/gap-plans",
      body: { kind: "matchedPosting", id: "p1" },
    });
  });

  it("opens the latest plan with its gaps ranked and cited", async () => {
    serve((_method, url) => {
      if (url === "/targets") return [option];
      if (url === "/gap-plans") return [summary];
      if (url === "/gap-plans/plan-1") return readyPlan;
      return null;
    });
    const shell = renderPlan();

    expect(
      await screen.findByText("01 · Demonstrated org-level influence"),
    ).toBeInTheDocument();
    expect(screen.getByText("+25 fit pts")).toBeInTheDocument();
    expect(screen.getByText("No evidence at all")).toBeInTheDocument();
    expect(
      screen.getByRole("img", {
        name: "Technical leadership: you 70, the bar is 90",
      }),
    ).toBeInTheDocument();
    expect(
      screen.getByText("GitHub · payments-svc — 38 merged PRs"),
    ).toBeInTheDocument();
    expect(screen.getByText("Platform Engineer")).toBeInTheDocument();
    expect(shell.setTarget).toHaveBeenCalledWith(
      "Senior Backend Engineer · Northwind Pay · 71%",
    );
  });

  it("ticks a task and counts one finished in another plan", async () => {
    const calls = serve((_method, url) => {
      if (url === "/targets") return [option];
      if (url === "/gap-plans") return [summary];
      if (url === "/gap-plans/plan-1") return readyPlan;
      if (url.startsWith("/gap-plan-tasks/")) return undefined;
      return null;
    });
    const user = userEvent.setup();
    renderPlan();

    const elsewhere = await screen.findByRole("checkbox", {
      name: /Present at all-hands/,
    });
    expect(elsewhere).toHaveAttribute("aria-checked", "true");
    expect(
      screen.getByText("Done in another plan — it counts here too."),
    ).toBeInTheDocument();

    await user.click(
      screen.getByRole("checkbox", { name: /Lead the checkout migration/ }),
    );
    expect(calls).toContainEqual({
      method: "PUT",
      url: "/gap-plan-tasks/t1",
      body: { done: true },
    });
  });

  it("pastes a JD as a private target before pricing a plan for it", async () => {
    const calls = serve((method, url) => {
      if (url === "/targets") return [option];
      if (url === "/gap-plans" && method === "GET") return [];
      if (url === "/job-descriptions") return { id: "jd-1" };
      if (url.startsWith("/gap-plans/cost-estimate"))
        return { cost_usd: "0.09", includes_scoring: true };
      return null;
    });
    const user = userEvent.setup();
    renderPlan();

    await user.click(await screen.findByRole("button", { name: "My own JD" }));
    await user.click(screen.getByRole("button", { name: "Use a sample" }));
    await user.click(screen.getByRole("button", { name: "Generate gap plan" }));

    expect(
      await screen.findByRole("region", { name: "Cost estimate" }),
    ).toHaveTextContent("reading and scoring the pasted job description");
    expect(calls).toContainEqual(
      expect.objectContaining({
        method: "POST",
        url: "/job-descriptions",
        body: expect.objectContaining({
          title: "Staff Platform Engineer",
          company_name: "Meridian Labs",
        }),
      }),
    );
    expect(calls.map((c) => c.url)).toContain(
      "/gap-plans/cost-estimate?kind=privatePosting&id=jd-1",
    );
  });

  it("sends a user without a model to set one up instead of pricing", async () => {
    serve((_method, url) => {
      if (url === "/targets") return [option];
      if (url === "/gap-plans") return [];
      return null;
    });
    const user = userEvent.setup();
    const shell = renderPlan({
      status: {
        me: null,
        credential: null,
        openQuestions: 0,
        confidence: null,
      },
    });

    await user.click(
      await screen.findByRole("button", { name: "Generate gap plan" }),
    );
    expect(shell.navigate).toHaveBeenCalledWith("model");
  });
});

describe("relative time", () => {
  const now = new Date("2026-09-23T12:00:00Z");

  it("reads like the prototype's history", () => {
    expect(ago("2026-09-23T11:59:30Z", now)).toBe("just now");
    expect(ago("2026-09-23T11:55:00Z", now)).toBe("5 min ago");
    expect(ago("2026-09-23T09:00:00Z", now)).toBe("3 hours ago");
    expect(ago("2026-09-22T11:00:00Z", now)).toBe("yesterday");
    expect(ago("2026-09-17T12:00:00Z", now)).toBe("6 days ago");
  });
});
