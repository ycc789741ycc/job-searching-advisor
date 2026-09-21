/**
 * Runtime configuration.
 *
 * Read from `window.__APP_CONFIG__`, which `config.js` defines. That file is
 * written by the container entrypoint from the environment, so one built
 * artifact is promoted through every environment rather than a bundle per
 * environment with values inlined at build time.
 *
 * Everything here reaches the browser, so nothing here is secret.
 */

export interface AppConfig {
  apiBaseUrl: string;
  clerkPublishableKey: string;
}

declare global {
  interface Window {
    __APP_CONFIG__?: Partial<AppConfig>;
  }
}

export function loadConfig(): AppConfig {
  const raw = window.__APP_CONFIG__;
  const missing = (["apiBaseUrl", "clerkPublishableKey"] as const).filter(
    (key) => !raw?.[key],
  );
  if (missing.length > 0) {
    throw new Error(
      `config.js is missing ${missing.join(", ")}. It is generated from the ` +
        `environment — check WEB_API_BASE_URL and WEB_CLERK_PUBLISHABLE_KEY.`,
    );
  }
  const config = raw as AppConfig;
  assertUsableClerkKey(config.clerkPublishableKey);
  return config;
}

/**
 * Clerk derives its frontend host by base64-decoding the part after the
 * `pk_test_` / `pk_live_` prefix, so a placeholder value fails deep inside the
 * SDK with nothing useful on screen. Checking the shape here turns that into a
 * sentence that names the variable to fix.
 */
function assertUsableClerkKey(key: string): void {
  const match = /^pk_(test|live)_(.+)$/.exec(key);
  const body = match?.[2];
  let host = "";
  if (body) {
    try {
      host = atob(body.replace(/-/g, "+").replace(/_/g, "/"));
    } catch {
      host = "";
    }
  }
  if (!host.includes(".")) {
    throw new Error(
      `WEB_CLERK_PUBLISHABLE_KEY is not a real Clerk publishable key ` +
        `(got "${key}"). Create a Clerk application, then set ` +
        `WEB_CLERK_PUBLISHABLE_KEY, CLERK_ISSUER, CLERK_JWKS_URL and ` +
        `CLERK_AUDIENCE in .env.`,
    );
  }
}
