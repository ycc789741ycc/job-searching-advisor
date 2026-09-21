import { useEffect, useRef, useState } from "react";
import { api } from "./api/client";
import type { Me } from "./api/types";
import { useAuth } from "./auth/AuthProvider";
import { SignInScreen } from "./auth/SignInScreen";
import { Button, Loading } from "./components/ui";
import { AiSettings } from "./features/AiSettings";
import { Clarify } from "./features/Clarify";
import { Connect } from "./features/Connect";
import {
  completeCallback,
  type CallbackOutcome,
} from "./features/oauthCallback";
import { Roles } from "./features/Roles";
import { Strengths } from "./features/Strengths";

type Screen = "connect" | "clarify" | "strengths" | "roles" | "settings";

const SCREENS: { id: Screen; label: string }[] = [
  { id: "connect", label: "Connect" },
  { id: "clarify", label: "Clarify" },
  { id: "strengths", label: "Strengths" },
  { id: "roles", label: "Role map" },
  { id: "settings", label: "Your model" },
];

export function App() {
  const { status } = useAuth();

  if (status === "loading") {
    // The refresh cookie is being exchanged; a reload should not flash the
    // sign-in screen while that happens.
    return (
      <div
        style={{ minHeight: "100vh", display: "grid", placeItems: "center" }}
      >
        <Loading what="your session" />
      </div>
    );
  }
  return status === "signed-in" ? <Shell /> : <SignInScreen />;
}

function Shell() {
  const { email, signOut } = useAuth();
  const [screen, setScreen] = useState<Screen>("connect");
  const [me, setMe] = useState<Me | null>(null);
  const [callback, setCallback] = useState<CallbackOutcome | null>(null);
  const handled = useRef(false);

  // Returning from GitHub or Jira lands on /connections/{kind}/callback.
  // Handled once per page load: the code it carries is single-use.
  useEffect(() => {
    if (handled.current) return;
    handled.current = true;
    void completeCallback(window.location, (url) =>
      window.history.replaceState(null, "", url),
    ).then((outcome) => {
      if (outcome) {
        setScreen("connect");
        setCallback(outcome);
      }
    });
  }, []);

  useEffect(() => {
    void api
      .get<Me>("/me")
      .then(setMe)
      .catch(() => setMe(null));
  }, []);

  return (
    <div style={{ maxWidth: 1080, margin: "0 auto", padding: "0 16px 64px" }}>
      <header
        style={{
          display: "flex",
          alignItems: "center",
          justifyContent: "space-between",
          gap: 16,
          padding: "16px 0",
          flexWrap: "wrap",
        }}
      >
        <strong>Job Searching Advisor</strong>
        <nav style={{ display: "flex", gap: 4, flexWrap: "wrap" }}>
          {SCREENS.map((item) => (
            <button
              key={item.id}
              onClick={() => setScreen(item.id)}
              aria-current={screen === item.id ? "page" : undefined}
              style={{
                border: "none",
                background:
                  screen === item.id ? "var(--surface-1)" : "transparent",
                color:
                  screen === item.id
                    ? "var(--text-primary)"
                    : "var(--text-secondary)",
                borderBottom:
                  screen === item.id
                    ? "2px solid var(--series-1)"
                    : "2px solid transparent",
                font: "inherit",
                fontWeight: 600,
                fontSize: 14,
                padding: "8px 12px",
                cursor: "pointer",
                borderRadius: "8px 8px 0 0",
              }}
            >
              {item.label}
            </button>
          ))}
        </nav>
        <span style={{ display: "flex", alignItems: "center", gap: 10 }}>
          <span className="muted" style={{ fontSize: 13 }}>
            {me?.email ?? email}
          </span>
          <Button variant="secondary" onClick={() => void signOut()}>
            Sign out
          </Button>
        </span>
      </header>

      {me?.background_jobs_paused && (
        <p
          role="alert"
          className="card"
          style={{
            color: "var(--status-critical)",
            fontSize: 13.5,
            marginBottom: 16,
          }}
        >
          <span aria-hidden="true">⚠</span> Background work is paused:{" "}
          {me.paused_reason}. Your reports will go out of date until this is
          fixed on the “Your model” screen.
        </p>
      )}

      <main>
        {screen === "connect" && <Connect callback={callback} />}
        {screen === "clarify" && <Clarify />}
        {screen === "strengths" && <Strengths />}
        {screen === "roles" && <Roles />}
        {screen === "settings" && <AiSettings />}
      </main>
    </div>
  );
}
