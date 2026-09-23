import "@testing-library/jest-dom/vitest";
import { fireEvent, render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import type { ResumeSummary, TailoredResume, TargetOption } from "../api/types";
import { ShellContext, type Shell } from "../shell/ShellContext";
import { ToastProvider } from "../shell/toast";
import { citeLine, Resume } from "./Resume";

const matched: TargetOption = {
  kind: "matchedPosting",
  id: "p1",
  title: "Senior Backend Engineer",
  role_name: "Senior Backend Engineer",
  role_id: "r1",
  company_name: "Northwind Pay",
  label: "Senior Backend Engineer · Northwind Pay",
  fit: 88,
  salary: { min: 178000, max: 196000, currency: "USD" },
  source_kind: "atsBoard",
  url: null,
  subscription_id: null,
};

const watched: TargetOption = {
  ...matched,
  kind: "subscription",
  id: "s1",
  title: "Staff Engineer",
  role_name: "Staff Engineer",
  company_name: "Kestrel Financial",
  label: "Staff Engineer · Kestrel Financial",
  fit: 64,
  salary: null,
  source_kind: "watchlist",
  subscription_id: "s1",
};

const summary: ResumeSummary = {
  id: "res-1",
  target: { kind: "matchedPosting", id: "p1" },
  label: matched.label,
  status: "ready",
  error: null,
  latest_version: 1,
  created_at: "2026-09-20T10:00:00Z",
  updated_at: "2026-09-20T10:00:00Z",
};

const version = {
  id: "v1",
  number: 1,
  label: matched.label,
  source: "generated" as const,
  model_id: "claude-opus-5",
  created_at: "2026-09-20T10:00:00Z",
};

const resume: TailoredResume = {
  ...summary,
  template: "warm",
  options: { metrics: true, reorder: true, trim: false },
  snapshot: {
    title: matched.title,
    company: matched.company_name,
    role_name: matched.role_name,
    fit: 88,
    basis: "role",
  },
  coverage: [
    {
      requirement: "Own a high-throughput payments service",
      verdict: "covered",
      evidence: [
        { id: "e1", reference: "GitHub · 38 PRs", fact: "payments-svc" },
      ],
    },
    { requirement: "Kubernetes in production", verdict: "gap", evidence: [] },
  ],
  version,
  content: {
    name: "Maya Lin Chen",
    headline: "Backend Engineer",
    contact: "maya@example.com",
    summary: "Builds payment systems.",
    experience: [
      {
        title: "Backend Engineer",
        org: "Kestrel Financial",
        when: "2022 — now",
        bullets: [
          {
            text: "Owned the retry layer for payments-svc",
            evidence_ids: ["e1"],
            origin: "written",
            answers: "Own a high-throughput payments service",
          },
        ],
      },
    ],
    skills: ["Go", "Postgres", "Kafka", "gRPC"],
  },
  evidence: { e1: { reference: "GitHub · 38 PRs", fact: "payments-svc" } },
  versions: [version],
  revisions: [],
};

function json(body: unknown, status = 200): Response {
  return new Response(body === undefined ? null : JSON.stringify(body), {
    status: body === undefined ? 204 : status,
    headers: { "Content-Type": "application/json" },
  });
}

function sse(events: [string, unknown][]): Response {
  const text = events
    .map(
      ([event, data]) => `event: ${event}\ndata: ${JSON.stringify(data)}\n\n`,
    )
    .join("");
  return new Response(
    new ReadableStream({
      start(controller) {
        const bytes = new TextEncoder().encode(text);
        // Split mid-event, as a network would.
        controller.enqueue(bytes.slice(0, 20));
        controller.enqueue(bytes.slice(20));
        controller.close();
      },
    }),
    { status: 200, headers: { "Content-Type": "text/event-stream" } },
  );
}

type Call = { method: string; url: string; body: unknown };

function serve(route: (call: Call) => Response | unknown) {
  const calls: Call[] = [];
  vi.stubGlobal(
    "fetch",
    vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
      const call = {
        method: init?.method ?? "GET",
        url: String(input).replace("http://api.test/api/v1", ""),
        body: init?.body ? JSON.parse(String(init.body)) : undefined,
      };
      calls.push(call);
      const result = route(call);
      return result instanceof Response ? result : json(result);
    }),
  );
  return calls;
}

function defaults(call: Call): unknown {
  if (call.url === "/targets") return [matched, watched];
  if (call.url === "/tailored-resumes" && call.method === "GET")
    return [summary];
  if (call.url === "/tailored-resumes/res-1") return resume;
  if (call.url === "/role-subscriptions") return [];
  return null;
}

function renderResume() {
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
  };
  render(
    <ShellContext.Provider value={shell}>
      <ToastProvider>
        <Resume />
      </ToastProvider>
    </ShellContext.Provider>,
  );
  return shell;
}

describe("résumé screen", () => {
  beforeEach(() => {
    window.__APP_CONFIG__ = { apiBaseUrl: "http://api.test" };
  });
  afterEach(() => vi.unstubAllGlobals());

  it("opens the latest résumé with cited lines and coverage", async () => {
    serve(defaults);
    const shell = renderResume();

    const page = await screen.findByRole("article", { name: "Résumé" });
    expect(within(page).getByText("Maya Lin Chen")).toBeInTheDocument();
    expect(
      within(page).getByText(
        "GitHub · 38 PRs — answers “Own a high-throughput payments service”",
      ),
    ).toBeInTheDocument();
    expect(screen.getByText("Covered")).toBeInTheDocument();
    expect(screen.getByText("Gap")).toBeInTheDocument();
    expect(
      screen.getByRole("button", { name: "Save this version" }),
    ).toBeDisabled();
    expect(shell.setTarget).toHaveBeenCalledWith(
      "Senior Backend Engineer · Northwind Pay · 88%",
    );
  });

  it("saves an edited line as a new version", async () => {
    const calls = serve((call) =>
      call.url === "/tailored-resumes/res-1/versions"
        ? { ...version, id: "v2", number: 2, source: "manual" }
        : defaults(call),
    );
    const user = userEvent.setup();
    renderResume();

    const line = await screen.findByText(
      "Owned the retry layer for payments-svc",
    );
    line.textContent = "Owned the retry layer, end to end";
    fireEvent.blur(line);

    const save = screen.getByRole("button", { name: "Save this version" });
    expect(save).toBeEnabled();
    expect(
      screen.getByRole("button", { name: "Export as PDF" }),
    ).toBeDisabled();
    await user.click(save);

    const posted = calls.find(
      (c) => c.url === "/tailored-resumes/res-1/versions",
    );
    expect(posted?.body).toMatchObject({
      content: {
        experience: [
          { bullets: [{ text: "Owned the retry layer, end to end" }] },
        ],
      },
    });
  });

  it("filters targets by where they came from", async () => {
    serve(defaults);
    const user = userEvent.setup();
    renderResume();

    await screen.findByText("Senior Backend Engineer · Northwind Pay", {
      selector: "span",
    });
    await user.click(screen.getByRole("button", { name: "Watchlist" }));

    expect(
      screen.queryByText("Senior Backend Engineer · Northwind Pay", {
        selector: "span",
      }),
    ).not.toBeInTheDocument();
    expect(
      screen.getByText("Staff Engineer · Kestrel Financial", {
        selector: "span",
      }),
    ).toBeInTheDocument();
  });

  it("streams a chat reply and applies its proposal only on request", async () => {
    const calls = serve((call) => {
      if (call.url === "/tailored-resumes/res-1/revisions")
        return sse([
          ["text", { text: "Shorter summary, " }],
          ["text", { text: "same lead line." }],
          [
            "proposal",
            {
              revision_id: "rev-1",
              reply: "Shorter summary, same lead line.",
              proposal: resume.content,
            },
          ],
        ]);
      if (call.url === "/tailored-resumes/res-1/revisions/rev-1/apply")
        return { ...version, id: "v2", number: 2, source: "chat" };
      return defaults(call);
    });
    const user = userEvent.setup();
    renderResume();

    await screen.findByRole("article", { name: "Résumé" });
    await user.click(
      screen.getByRole("button", { name: "Make the summary shorter" }),
    );

    expect(
      await screen.findByText("Shorter summary, same lead line."),
    ).toBeInTheDocument();
    const posted = calls.find(
      (c) => c.url === "/tailored-resumes/res-1/revisions",
    );
    expect(posted?.body).toMatchObject({
      message: "Make the summary shorter",
      content: { name: "Maya Lin Chen" },
    });
    expect(calls.some((c) => c.url.endsWith("/apply"))).toBe(false);

    await user.click(screen.getByRole("button", { name: "Apply" }));
    expect(calls.some((c) => c.url.endsWith("/revisions/rev-1/apply"))).toBe(
      true,
    );
  });

  it("shows a rejected revision as an error, with nothing to apply", async () => {
    serve((call) =>
      call.url === "/tailored-resumes/res-1/revisions"
        ? sse([
            ["text", { text: "Added it." }],
            [
              "error",
              {
                code: "ai_output_invalid",
                message: "the proposed revision was rejected",
              },
            ],
          ])
        : defaults(call),
    );
    const user = userEvent.setup();
    renderResume();

    // The chat opens once the résumé has loaded.
    await screen.findByRole("article", { name: "Résumé" });
    const input = screen.getByRole("textbox", { name: "Ask for a change" });
    expect(input).toBeEnabled();
    await user.type(input, "Add a promotion{Enter}");

    expect(
      await screen.findByText(/the proposed revision was rejected/),
    ).toBeInTheDocument();
    expect(
      screen.queryByRole("button", { name: "Apply" }),
    ).not.toBeInTheDocument();
  });
});

describe("the grey note under a line", () => {
  const evidence = { e1: { reference: "Jira PAY-412", fact: "…" } };

  it("names its source and what it answers", () => {
    expect(
      citeLine(
        { text: "x", evidence_ids: ["e1"], origin: "written", answers: "Lead" },
        evidence,
      ),
    ).toBe("Jira PAY-412 — answers “Lead”");
  });

  it("says plainly when a line is the user's own and cites nothing", () => {
    expect(
      citeLine(
        { text: "x", evidence_ids: [], origin: "yours", answers: null },
        evidence,
      ),
    ).toBe("Your edit — no source cited");
  });
});
