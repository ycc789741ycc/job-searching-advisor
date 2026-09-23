/**
 * Reading why a Google sign-in did not finish.
 *
 * The API ends every Google sign-in by sending the browser back here. On
 * failure it adds `?sign_in_error=<code>`, a stable code and nothing else, so
 * no provider detail reaches the page. This turns the code into something a
 * person can act on.
 */

const MESSAGES: Record<string, string> = {
  declined: "Google sign-in was cancelled, so nothing changed.",
  state_mismatch:
    "That Google sign-in could not be matched to this browser. Please try again.",
  expired: "That Google sign-in took too long. Please try again.",
  nonce_mismatch:
    "That Google sign-in could not be matched to this browser. Please try again.",
  unverified_email:
    "Google has not verified that address yet, so it cannot be used to sign in.",
  account_conflict:
    "That address is already linked to a different Google account.",
  provider_failed:
    "Google did not complete the sign-in. Please try again in a moment.",
  not_configured: "Google sign-in is not set up on this server.",
};

export const PARAM = "sign_in_error";

/** The message for the current URL, or null when it carries none. Pure. */
export function readSignInError(search: string): string | null {
  const code = new URLSearchParams(search).get(PARAM);
  if (!code) return null;
  return MESSAGES[code] ?? "Google sign-in did not finish. Please try again.";
}

/** The same URL without the error, so a reload does not show it again. */
export function withoutSignInError(pathname: string, search: string): string {
  const params = new URLSearchParams(search);
  params.delete(PARAM);
  const rest = params.toString();
  return rest ? `${pathname}?${rest}` : pathname;
}
