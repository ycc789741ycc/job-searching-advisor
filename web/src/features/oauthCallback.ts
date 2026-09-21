/**
 * Receiving the browser back from a connector's OAuth consent screen.
 *
 * The provider redirects with a GET to `/connections/{kind}/callback`, carrying
 * `code` and `state` — or `error` if the person declined. That has to land in
 * the SPA rather than the API, because exchanging the code needs the user's
 * access token, and that lives only in this page's memory.
 */

import { api } from "../api/client";

export const CONNECTORS = ["github", "jira"] as const;
export type ConnectorKind = (typeof CONNECTORS)[number];

const CALLBACK_PATH = /^\/connections\/([a-z]+)\/callback\/?$/;

export type CallbackParams =
  | { kind: ConnectorKind; code: string; state: string }
  | { kind: ConnectorKind; error: string };

/** What the current URL says, or null when this is not a callback. Pure. */
export function parseCallback(pathname: string, search: string): CallbackParams | null {
  const match = CALLBACK_PATH.exec(pathname);
  const kind = match?.[1];
  if (!kind || !(CONNECTORS as readonly string[]).includes(kind)) return null;

  const params = new URLSearchParams(search);
  const error = params.get("error");
  if (error) {
    return {
      kind: kind as ConnectorKind,
      error: params.get("error_description") ?? readableError(error),
    };
  }

  const code = params.get("code");
  const state = params.get("state");
  if (!code || !state) {
    return {
      kind: kind as ConnectorKind,
      error: "The sign-in came back incomplete. Please connect again.",
    };
  }
  return { kind: kind as ConnectorKind, code, state };
}

function readableError(code: string): string {
  if (code === "access_denied") return "Access was not granted, so nothing was connected.";
  return `The provider reported an error (${code}). Please connect again.`;
}

export interface CallbackOutcome {
  kind: ConnectorKind;
  connected: boolean;
  message: string;
}

const NAMES: Record<ConnectorKind, string> = { github: "GitHub", jira: "Jira" };

/**
 * Finish the connection, if this page load is a callback.
 *
 * The URL is cleared *before* the request goes out. The code is single-use, so
 * a reload — or a second run of the effect that calls this — must not present
 * it again, which would fail and overwrite the real outcome with an error.
 */
export async function completeCallback(
  location: Pick<Location, "pathname" | "search">,
  replaceUrl: (url: string) => void,
): Promise<CallbackOutcome | null> {
  const params = parseCallback(location.pathname, location.search);
  if (!params) return null;

  replaceUrl("/");

  if ("error" in params) {
    return { kind: params.kind, connected: false, message: params.error };
  }

  try {
    await api.post(`/connections/${params.kind}/callback`, {
      code: params.code,
      state: params.state,
    });
    return {
      kind: params.kind,
      connected: true,
      message: `${NAMES[params.kind]} is connected. The first sync is running now.`,
    };
  } catch (caught) {
    return {
      kind: params.kind,
      connected: false,
      message: caught instanceof Error ? caught.message : "Connecting failed.",
    };
  }
}
