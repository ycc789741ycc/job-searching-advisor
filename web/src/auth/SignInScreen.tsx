import { useEffect, useState, type CSSProperties, type FormEvent } from "react";
import { Button, ErrorNote, Field } from "../components/ui";
import { useAuth } from "./AuthProvider";
import { googleStartUrl, signInMethods } from "./session";
import { readSignInError, withoutSignInError } from "./signInError";

const MIN_PASSWORD_LENGTH = 12;

/** Sign in or create an account. One form, two modes. */
export function SignInScreen() {
  const { signIn, register } = useAuth();
  const [mode, setMode] = useState<"sign-in" | "register">("sign-in");
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [busy, setBusy] = useState(false);
  // A Google sign-in that did not finish comes back with its reason in the
  // URL. Read purely here; the effect below removes it.
  const [error, setError] = useState<string | null>(() =>
    readSignInError(window.location.search),
  );
  const [googleOffered, setGoogleOffered] = useState(false);

  const registering = mode === "register";

  useEffect(() => {
    const { pathname, search } = window.location;
    if (readSignInError(search) !== null) {
      window.history.replaceState(
        null,
        "",
        withoutSignInError(pathname, search),
      );
    }
  }, []);

  useEffect(() => {
    let cancelled = false;
    signInMethods()
      .then((methods) => !cancelled && setGoogleOffered(methods.google))
      .catch(() => !cancelled && setGoogleOffered(false));
    return () => {
      cancelled = true;
    };
  }, []);

  async function submit(event: FormEvent) {
    event.preventDefault();
    setBusy(true);
    setError(null);
    try {
      await (registering ? register(email, password) : signIn(email, password));
    } catch (caught) {
      setError(
        caught instanceof Error ? caught.message : "Something went wrong.",
      );
    } finally {
      setBusy(false);
    }
  }

  return (
    <div
      className="auto-grid"
      style={
        {
          "--col": "360px",
          "--gap": "20px",
          minHeight: "100vh",
          alignItems: "center",
        } as CSSProperties
      }
    >
      <div style={{ padding: "56px 48px", maxWidth: 580 }}>
        <div
          className="brand"
          style={{ padding: 0, marginBottom: 36, fontSize: 20 }}
        >
          <span
            className="brand-dot"
            style={{ width: 32, height: 32 }}
            aria-hidden="true"
          />
          Job Searching Advisor
        </div>
        <h1 style={{ fontSize: 44, lineHeight: 1.08, marginBottom: 16 }}>
          Your next role, read from the work you already did.
        </h1>
        <p className="lead" style={{ fontSize: 17, maxWidth: "46ch" }}>
          Connect GitHub and Jira. We read what you actually shipped, score it
          against real market bars, and plan the distance to the role you pick.
        </p>

        <form
          onSubmit={submit}
          style={{ display: "grid", gap: 4, maxWidth: 430, marginTop: 30 }}
        >
          <h2 style={{ fontSize: 21, margin: "0 0 10px" }}>
            {registering ? "Create an account" : "Sign in"}
          </h2>

          <Field label="Email">
            <input
              className="input"
              type="email"
              value={email}
              autoComplete="email"
              placeholder="you@work.com"
              required
              onChange={(event) => setEmail(event.target.value)}
            />
          </Field>

          <Field
            label="Password"
            {...(registering
              ? {
                  hint: `At least ${MIN_PASSWORD_LENGTH} characters. A memorable phrase beats a short, punctuated one.`,
                }
              : {})}
          >
            <input
              className="input"
              type="password"
              value={password}
              autoComplete={registering ? "new-password" : "current-password"}
              required
              minLength={registering ? MIN_PASSWORD_LENGTH : 1}
              onChange={(event) => setPassword(event.target.value)}
            />
          </Field>

          <ErrorNote error={error} />

          <div className="row">
            <Button type="submit" busy={busy} disabled={!email || !password}>
              {registering ? "Create account" : "Sign in"}
            </Button>
            <span className="subcopy" style={{ fontSize: 13.5 }}>
              {registering ? "Already have an account?" : "No account yet?"}
            </span>
            <Button
              variant="ghost"
              onClick={() => {
                setMode(registering ? "sign-in" : "register");
                setError(null);
              }}
            >
              {registering ? "Sign in instead" : "Create one"}
            </Button>
          </div>

          {googleOffered && (
            <div style={{ marginTop: 14 }}>
              <div
                className="muted"
                style={{ fontSize: 12.5, margin: "0 0 8px" }}
                aria-hidden="true"
              >
                or
              </div>
              {/* A link, not a fetch: the browser itself goes to Google. */}
              <a className="btn btn-secondary" href={googleStartUrl()}>
                Continue with Google
              </a>
            </div>
          )}

          {/* Said plainly rather than discovered later. */}
          <p
            className="muted"
            style={{ fontSize: 12.5, lineHeight: 1.5, marginTop: 10 }}
          >
            You bring your own AI provider and key after signing in — nothing is
            analysed until you do. There is no password reset yet, and your
            address is not verified. Keep your password somewhere safe.
            {googleOffered &&
              " Signing in with Google proves your address: an account with the same address is linked to Google, and any password on it stops working."}
          </p>
        </form>
      </div>

      <div style={{ padding: 40, display: "flex", justifyContent: "center" }}>
        <div
          className="panel"
          style={{
            width: "100%",
            maxWidth: 420,
            boxShadow: "var(--shadow-md)",
          }}
        >
          <div className="row" style={{ gap: 8, marginBottom: 12 }}>
            <span className="tag tag-accent">Skill radar</span>
            <span className="tag tag-accent-2">Salary bubbles</span>
            <span className="tag tag-outline">Gap plan</span>
          </div>
          <div className="divided">
            {PITCH.map((point, index) => (
              <div key={point.title} style={{ display: "flex", gap: 14 }}>
                <div
                  aria-hidden="true"
                  style={{
                    width: 34,
                    height: 34,
                    flex: "0 0 auto",
                    borderRadius: 999,
                    background: "var(--color-accent-2-200)",
                    color: "var(--color-accent-2-800)",
                    display: "flex",
                    alignItems: "center",
                    justifyContent: "center",
                    fontFamily: "var(--font-heading)",
                    fontSize: 14,
                  }}
                >
                  {index + 1}
                </div>
                <div>
                  <div style={{ fontWeight: 700, fontSize: 15 }}>
                    {point.title}
                  </div>
                  <div className="subcopy" style={{ fontSize: 13.5 }}>
                    {point.note}
                  </div>
                </div>
              </div>
            ))}
          </div>
        </div>
      </div>
    </div>
  );
}

const PITCH = [
  {
    title: "Evidence, not self-assessment",
    note: "Every score cites the pull request, ticket or résumé line it came from.",
  },
  {
    title: "Roles from real openings",
    note: "Grouped from public job boards in the markets you choose.",
  },
  {
    title: "A plan to close the distance",
    note: "Milestones against the one role and company you pick.",
  },
  {
    title: "Your model, your key",
    note: "Every AI call runs on a provider you already pay for.",
  },
];
