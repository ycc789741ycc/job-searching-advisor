/**
 * The one place the SPA talks to the API.
 *
 * Every call carries the access token the auth provider holds. Errors arrive as
 * `{ error: { code, message } }` and are turned into an `ApiError` so features
 * can show the message near the thing that failed rather than a generic banner.
 */

import { loadConfig } from "../config";

/**
 * Resolved on first request, never at import time.
 *
 * Reading configuration while this module is being imported makes a bad value
 * throw during the import graph's evaluation — before any error handling in
 * main.tsx has had a chance to run — and the page renders nothing at all.
 */
let base: string | null = null;

function apiBase(): string {
  base ??= loadConfig().apiBaseUrl;
  return base;
}

export class ApiError extends Error {
  constructor(
    readonly code: string,
    message: string,
    readonly status: number,
  ) {
    super(message);
    this.name = "ApiError";
  }
}

type TokenSource = () => Promise<string | null>;

let getToken: TokenSource = async () => null;

/** Registered by the auth provider; not a React hook. */
export function setTokenSource(source: TokenSource): void {
  getToken = source;
}

async function request<T>(path: string, init: RequestInit = {}): Promise<T> {
  const token = await getToken();
  const headers = new Headers(init.headers);
  if (token) headers.set("authorization", `Bearer ${token}`);
  if (init.body && !(init.body instanceof FormData)) {
    headers.set("content-type", "application/json");
  }

  const response = await fetch(`${apiBase()}/api/v1${path}`, {
    ...init,
    headers,
  });

  if (response.status === 204) return undefined as T;

  const text = await response.text();
  const payload: unknown = text ? JSON.parse(text) : null;

  if (!response.ok) {
    const envelope = payload as { error?: { code?: string; message?: string } };
    throw new ApiError(
      envelope?.error?.code ?? "unknown",
      envelope?.error?.message ?? `Request failed (${response.status})`,
      response.status,
    );
  }
  return payload as T;
}

export const api = {
  get: <T>(path: string) => request<T>(path),
  post: <T>(path: string, body?: unknown) =>
    request<T>(path, {
      method: "POST",
      body: body ? JSON.stringify(body) : null,
    }),
  put: <T>(path: string, body: unknown) =>
    request<T>(path, { method: "PUT", body: JSON.stringify(body) }),
  del: <T>(path: string) => request<T>(path, { method: "DELETE" }),
  upload: <T>(path: string, file: File) => {
    const form = new FormData();
    form.append("file", file);
    return request<T>(path, { method: "POST", body: form });
  },
};

export interface ServerEvent {
  event: string;
  data: string;
}

/** Split an SSE buffer into complete events and what is left over. Pure. */
export function parseEvents(buffer: string): {
  events: ServerEvent[];
  rest: string;
} {
  const normalised = buffer.replace(/\r\n/g, "\n");
  const blocks = normalised.split("\n\n");
  const rest = blocks.pop() ?? "";
  const events: ServerEvent[] = [];
  for (const block of blocks) {
    let event = "message";
    const data: string[] = [];
    for (const line of block.split("\n")) {
      if (line.startsWith("event:")) event = line.slice(6).trim();
      else if (line.startsWith("data:"))
        data.push(line.slice(5).replace(/^ /, ""));
    }
    if (data.length > 0) events.push({ event, data: data.join("\n") });
  }
  return { events, rest };
}

/**
 * POST and read Server-Sent Events as they arrive.
 *
 * `EventSource` can neither POST a body nor send the bearer token, so the
 * résumé chat reads the stream itself. A refusal before streaming starts
 * throws an `ApiError`, as any other call would.
 */
export async function streamEvents(
  path: string,
  body: unknown,
  onEvent: (event: ServerEvent) => void,
): Promise<void> {
  const token = await getToken();
  const headers = new Headers({
    "content-type": "application/json",
    accept: "text/event-stream",
  });
  if (token) headers.set("authorization", `Bearer ${token}`);
  const response = await fetch(`${apiBase()}/api/v1${path}`, {
    method: "POST",
    headers,
    body: JSON.stringify(body),
  });
  if (!response.ok || !response.body) {
    const text = await response.text();
    const envelope = (text ? JSON.parse(text) : null) as {
      error?: { code?: string; message?: string };
    } | null;
    throw new ApiError(
      envelope?.error?.code ?? "unknown",
      envelope?.error?.message ?? `Request failed (${response.status})`,
      response.status,
    );
  }

  const reader = response.body.getReader();
  const decoder = new TextDecoder();
  let buffer = "";
  for (;;) {
    const { value, done } = await reader.read();
    if (done) break;
    buffer += decoder.decode(value, { stream: true });
    const { events, rest } = parseEvents(buffer);
    buffer = rest;
    events.forEach(onEvent);
  }
  const { events } = parseEvents(`${buffer}\n\n`);
  events.forEach(onEvent);
}
