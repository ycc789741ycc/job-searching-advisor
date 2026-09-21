import { useState, type FormEvent } from "react";
import { Button, ErrorNote, Field, inputStyle } from "../components/ui";
import { useAuth } from "./AuthProvider";

const MIN_PASSWORD_LENGTH = 12;

/** Sign in or create an account. One form, two modes. */
export function SignInScreen() {
  const { signIn, register } = useAuth();
  const [mode, setMode] = useState<"sign-in" | "register">("sign-in");
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const registering = mode === "register";

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
      style={{
        minHeight: "100vh",
        display: "grid",
        placeItems: "center",
        padding: 24,
      }}
    >
      <div style={{ width: "100%", maxWidth: 400 }}>
        <h1 style={{ textAlign: "center" }}>Job Searching Advisor</h1>
        <p
          className="secondary"
          style={{ textAlign: "center", margin: "0 0 24px", fontSize: 14.5 }}
        >
          Turn the work you have actually done into a picture of where you stand
          and what to aim at next.
        </p>

        <form className="card" onSubmit={submit}>
          <h2 style={{ marginTop: 0, fontSize: 17 }}>
            {registering ? "Create an account" : "Sign in"}
          </h2>

          <Field label="Email">
            <input
              style={inputStyle}
              type="email"
              value={email}
              autoComplete="email"
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
              style={inputStyle}
              type="password"
              value={password}
              autoComplete={registering ? "new-password" : "current-password"}
              required
              minLength={registering ? MIN_PASSWORD_LENGTH : 1}
              onChange={(event) => setPassword(event.target.value)}
            />
          </Field>

          <ErrorNote error={error} />

          <Button type="submit" busy={busy} disabled={!email || !password}>
            {registering ? "Create account" : "Sign in"}
          </Button>

          <p className="secondary" style={{ fontSize: 13.5, marginBottom: 0 }}>
            {registering ? "Already have an account?" : "No account yet?"}{" "}
            <button
              type="button"
              onClick={() => {
                setMode(registering ? "sign-in" : "register");
                setError(null);
              }}
              style={{
                background: "none",
                border: "none",
                padding: 0,
                font: "inherit",
                color: "var(--series-1)",
                cursor: "pointer",
                textDecoration: "underline",
              }}
            >
              {registering ? "Sign in" : "Create one"}
            </button>
          </p>
        </form>

        {/* Said plainly rather than discovered later. */}
        <p
          className="muted"
          style={{ fontSize: 12.5, textAlign: "center", marginTop: 14 }}
        >
          There is no password reset yet, and your address is not verified. Keep
          your password somewhere safe.
        </p>
      </div>
    </div>
  );
}
