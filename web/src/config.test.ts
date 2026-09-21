import { afterEach, describe, expect, it } from "vitest";
import { loadConfig } from "./config";

function setConfig(value: unknown): void {
  (window as unknown as { __APP_CONFIG__?: unknown }).__APP_CONFIG__ = value;
}

// A real Clerk key is the prefix plus a base64 frontend host.
const REAL_KEY = `pk_test_${btoa("clerk.example.accounts.dev")}`;

afterEach(() => setConfig(undefined));

describe("runtime configuration", () => {
  it("accepts a well-formed config", () => {
    setConfig({
      apiBaseUrl: "http://localhost:8000",
      clerkPublishableKey: REAL_KEY,
    });
    expect(loadConfig()).toEqual({
      apiBaseUrl: "http://localhost:8000",
      clerkPublishableKey: REAL_KEY,
    });
  });

  it("names the variables that are missing", () => {
    setConfig({ apiBaseUrl: "http://localhost:8000" });
    expect(() => loadConfig()).toThrow(/clerkPublishableKey/);
  });

  it("explains when config.js was never written at all", () => {
    setConfig(undefined);
    expect(() => loadConfig()).toThrow(/WEB_API_BASE_URL/);
  });

  it("rejects a placeholder Clerk key by name", () => {
    // Clerk base64-decodes the key to find its frontend host, so a placeholder
    // fails deep inside the SDK with nothing useful on screen. Catch it here.
    setConfig({
      apiBaseUrl: "http://localhost:8000",
      clerkPublishableKey: "pk_test_local_placeholder",
    });
    expect(() => loadConfig()).toThrow(
      /WEB_CLERK_PUBLISHABLE_KEY is not a real Clerk/,
    );
  });

  it("rejects a key that decodes to something that is not a host", () => {
    setConfig({
      apiBaseUrl: "http://localhost:8000",
      clerkPublishableKey: `pk_live_${btoa("nonsense")}`,
    });
    expect(() => loadConfig()).toThrow(/not a real Clerk/);
  });

  it("accepts a live key as readily as a test key", () => {
    const live = `pk_live_${btoa("clerk.example.com")}`;
    setConfig({
      apiBaseUrl: "https://api.example.com",
      clerkPublishableKey: live,
    });
    expect(loadConfig().clerkPublishableKey).toBe(live);
  });
});
