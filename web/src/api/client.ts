/**
 * The one place the SPA talks to the API.
 *
 * Every call carries the Clerk JWT. Errors arrive as
 * `{ error: { code, message } }` and are turned into an `ApiError` so features
 * can show the message near the thing that failed rather than a generic banner.
 */

import { loadConfig } from "../config";

const BASE = loadConfig().apiBaseUrl;

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

export function useTokenSource(source: TokenSource): void {
  getToken = source;
}

async function request<T>(path: string, init: RequestInit = {}): Promise<T> {
  const token = await getToken();
  const headers = new Headers(init.headers);
  if (token) headers.set("authorization", `Bearer ${token}`);
  if (init.body && !(init.body instanceof FormData)) {
    headers.set("content-type", "application/json");
  }

  const response = await fetch(`${BASE}/api/v1${path}`, { ...init, headers });

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
