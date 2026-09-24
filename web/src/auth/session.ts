/**
 * Talking to our own auth endpoints.
 *
 * The access token comes back in the body and is held in memory only. The
 * refresh token never appears here at all — it is an httpOnly cookie, so this
 * code cannot read it, which is exactly the point: a cross-site scripting bug
 * cannot steal a session.
 *
 * Every call sets `credentials: "include"` so the browser attaches that cookie.
 */

import { loadConfig } from "../config";

export interface Session {
  accountId: string;
  email: string;
  accessToken: string;
  /** Epoch milliseconds. Used to refresh before a request would fail. */
  expiresAt: number;
}

export class AuthError extends Error {
  constructor(
    message: string,
    readonly code: string,
  ) {
    super(message);
    this.name = "AuthError";
  }
}

interface SessionPayload {
  account_id: string;
  email: string;
  access_token: string;
  expires_in: number;
}

async function post(path: string, body?: unknown): Promise<Response> {
  return fetch(`${loadConfig().apiBaseUrl}/api/v1/auth${path}`, {
    method: "POST",
    // Sends the httpOnly refresh cookie; without this the browser withholds it
    // on a cross-origin call and every refresh looks like a signed-out user.
    credentials: "include",
    ...(body
      ? {
          headers: { "content-type": "application/json" },
          body: JSON.stringify(body),
        }
      : {}),
  });
}

async function toSession(response: Response): Promise<Session> {
  const text = await response.text();
  const payload: unknown = text ? JSON.parse(text) : null;

  if (!response.ok) {
    const envelope = payload as { error?: { code?: string; message?: string } };
    throw new AuthError(
      envelope?.error?.message ?? "Sign-in failed. Please try again.",
      envelope?.error?.code ?? "unknown",
    );
  }

  const data = payload as SessionPayload;
  return {
    accountId: data.account_id,
    email: data.email,
    accessToken: data.access_token,
    expiresAt: Date.now() + data.expires_in * 1000,
  };
}

export async function register(
  email: string,
  password: string,
): Promise<Session> {
  return toSession(await post("/register", { email, password }));
}

export async function signIn(
  email: string,
  password: string,
): Promise<Session> {
  return toSession(await post("/sign-in", { email, password }));
}

/** Exchanges the refresh cookie for a new pair. Rejects when there is none. */
export async function refresh(): Promise<Session> {
  return toSession(await post("/refresh"));
}

export async function signOut(): Promise<void> {
  await post("/sign-out");
}

export interface SignInMethods {
  password: boolean;
  google: boolean;
}

/** Which ways in to offer. Google is on only when the server is set up for it. */
export async function signInMethods(): Promise<SignInMethods> {
  const response = await fetch(
    `${loadConfig().apiBaseUrl}/api/v1/auth/methods`,
  );
  if (!response.ok) return { password: true, google: false };
  const payload = (await response.json()) as Partial<SignInMethods> | null;
  return { password: true, google: payload?.google === true };
}

/**
 * Where "Continue with Google" goes. A full-page navigation, not a fetch: the
 * API sends the browser on to Google and, afterwards, back to this app with
 * the refresh cookie set, which the refresh on load then picks up.
 */
export function googleStartUrl(): string {
  return `${loadConfig().apiBaseUrl}/api/v1/auth/google/start`;
}
