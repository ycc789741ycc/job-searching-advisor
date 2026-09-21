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
  return raw as AppConfig;
}
