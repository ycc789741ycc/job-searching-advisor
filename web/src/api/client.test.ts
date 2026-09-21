import { describe, expect, it, vi } from "vitest";
import { api } from "./client";

/**
 * The regression this guards: resolving configuration while this module is
 * imported made a bad value throw during import-graph evaluation, before any
 * error handling could run, and the page rendered nothing at all.
 */
describe("api client", () => {
  it("does not read configuration at import time", () => {
    // The import above already happened with no window.__APP_CONFIG__ set.
    // Reaching this line at all is the assertion.
    expect(api).toBeDefined();
  });

  it("reads configuration on the first request, not before", async () => {
    (window as unknown as { __APP_CONFIG__?: unknown }).__APP_CONFIG__ = {
      apiBaseUrl: "http://api.test",
    };
    const fetchMock = vi
      .fn()
      .mockResolvedValue(new Response("{}", { status: 200 }));
    vi.stubGlobal("fetch", fetchMock);

    await api.get("/health");

    expect(fetchMock).toHaveBeenCalledWith(
      "http://api.test/api/v1/health",
      expect.anything(),
    );
    vi.unstubAllGlobals();
  });
});
