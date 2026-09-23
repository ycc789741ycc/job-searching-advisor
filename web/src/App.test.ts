import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { loadStatus } from "./App";

function json(body: unknown, status = 200): Response {
  return new Response(JSON.stringify(body), {
    status,
    headers: { "Content-Type": "application/json" },
  });
}

describe("shell status", () => {
  beforeEach(() => {
    (window as unknown as { __APP_CONFIG__?: unknown }).__APP_CONFIG__ = {
      apiBaseUrl: "http://api.test",
    };
  });
  afterEach(() => vi.unstubAllGlobals());

  it("counts open questions and averages confidence across dimensions", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn(async (input: RequestInfo | URL) => {
        const url = String(input);
        if (url.endsWith("/questions"))
          return json([{ answer: null }, { answer: "yes" }, { answer: null }]);
        if (url.endsWith("/assessments/latest"))
          return json({
            dimensions: [{ confidence: 0.8 }, { confidence: 0.9 }],
          });
        if (url.endsWith("/ai-credential")) return json(null);
        return json({ id: "u1", email: "maya@example.com" });
      }),
    );

    const status = await loadStatus();

    expect(status.openQuestions).toBe(2);
    expect(status.confidence).toBe(85);
    expect(status.credential).toBeNull();
  });

  it("keeps the rest when one piece fails", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn(async (input: RequestInfo | URL) =>
        String(input).endsWith("/questions")
          ? json({ error: { code: "internal", message: "boom" } }, 500)
          : String(input).endsWith("/me")
            ? json({ id: "u1", email: "maya@example.com" })
            : json(null),
      ),
    );

    const status = await loadStatus();

    expect(status.openQuestions).toBe(0);
    expect(status.confidence).toBeNull();
    expect(status.me?.email).toBe("maya@example.com");
  });
});
