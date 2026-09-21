import { afterEach, describe, expect, it } from "vitest";
import { loadConfig } from "./config";

function setConfig(value: unknown): void {
  (window as unknown as { __APP_CONFIG__?: unknown }).__APP_CONFIG__ = value;
}

afterEach(() => setConfig(undefined));

describe("runtime configuration", () => {
  it("accepts a well-formed config", () => {
    setConfig({ apiBaseUrl: "http://localhost:8000" });
    expect(loadConfig()).toEqual({ apiBaseUrl: "http://localhost:8000" });
  });

  it("names the variable to fix when config.js was never written", () => {
    setConfig(undefined);
    expect(() => loadConfig()).toThrow(/WEB_API_BASE_URL/);
  });

  it("rejects an empty base URL rather than building requests against nothing", () => {
    setConfig({ apiBaseUrl: "" });
    expect(() => loadConfig()).toThrow(/apiBaseUrl/);
  });
});
