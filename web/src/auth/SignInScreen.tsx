import { useEffect, useState, type FormEvent } from "react";
import { AppIcon } from "../components/AppIcon";
import { PRIVACY_PATH } from "../features/PrivacyPolicy";
import { Button, ErrorNote, Field } from "../components/ui";
import { useAuth } from "./AuthProvider";
import { googleStartUrl, signInMethods, type SignInMethods } from "./session";
import { SignInIllustration } from "./SignInIllustration";
import { readSignInError, withoutSignInError } from "./signInError";

const MIN_PASSWORD_LENGTH = 12;

/** Until the server says otherwise: a password, and nothing else. */
const NO_OUTSIDE_METHODS: SignInMethods = {
  password: true,
  google: false,
  platform_ai: false,
};

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
  const [methods, setMethods] = useState<SignInMethods>(NO_OUTSIDE_METHODS);

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
      .then((offered) => !cancelled && setMethods(offered))
      .catch(() => !cancelled && setMethods(NO_OUTSIDE_METHODS));
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
    <div className="sign-in">
      <div className="brand sign-in-brand">
        <AppIcon size={32} />
        CareerPolaris
      </div>

      <div className="sign-in-pitch">
        <SignInIllustration />
        <div>
          <h1 className="sign-in-headline">
            Know your strengths. Find your next role. Tailor your résumé to it.
          </h1>
          <p className="lead sign-in-lead">
            CareerPolaris reads your evidence from GitHub, Jira and your past
            résumé, then backs every strength, role match and résumé line with
            it.
          </p>
        </div>
      </div>

      <div className="sign-in-aside">
        <div className="sign-in-card">
          <form onSubmit={submit} style={{ display: "grid", gap: 4 }}>
            <h2 className="sign-in-heading">
              {registering ? "Create your account" : "Welcome back"}
            </h2>

            {methods.google && (
              <>
                {/* A link, not a fetch: the browser itself goes to Google. */}
                <a
                  className="btn btn-secondary sign-in-google"
                  href={googleStartUrl()}
                >
                  Continue with Google
                </a>
                <div className="sign-in-divider">or with email</div>
              </>
            )}

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

            <Button
              type="submit"
              busy={busy}
              disabled={!email || !password}
              block
            >
              {registering ? "Create account" : "Sign in"}
            </Button>

            <div className="sign-in-switch">
              {registering
                ? "Already have an account?"
                : "New to CareerPolaris?"}
              <Button
                variant="ghost"
                onClick={() => {
                  setMode(registering ? "sign-in" : "register");
                  setError(null);
                }}
              >
                {registering ? "Sign in" : "Create an account"}
              </Button>
            </div>

            {/* Said plainly rather than discovered later. */}
            <p className="sign-in-footnote">
              {methods.platform_ai
                ? "Sign in with Google to start on CareerPolaris AI's free monthly quota, or add your own AI provider and key after signing in."
                : "After signing in you add your own AI provider and key; nothing is analysed until you do."}{" "}
              No password reset yet, and addresses are not verified.
              {methods.google &&
                " Signing in with Google proves your address: an account with the same address is linked to Google, and any password on it stops working."}{" "}
              <a href={PRIVACY_PATH}>Privacy policy</a>
            </p>
          </form>
        </div>
      </div>
    </div>
  );
}
