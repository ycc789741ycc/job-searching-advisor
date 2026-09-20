import { SignedIn, SignedOut, SignIn, UserButton, useAuth } from "@clerk/clerk-react";
import { useEffect, useState } from "react";
import { api, useTokenSource } from "./api/client";
import type { Me } from "./api/types";
import { AiSettings } from "./features/AiSettings";
import { Clarify } from "./features/Clarify";
import { Connect } from "./features/Connect";
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
  return (
    <>
      <SignedOut>
        <div
          style={{
            minHeight: "100vh",
            display: "grid",
            placeItems: "center",
            padding: 24,
          }}
        >
          <div style={{ textAlign: "center" }}>
            <h1>Job Searching Advisor</h1>
            <p className="secondary" style={{ maxWidth: 420, margin: "0 auto 24px" }}>
              Turn the work you have actually done into a picture of where you
              stand and what to aim at next.
            </p>
            <SignIn routing="hash" />
          </div>
        </div>
      </SignedOut>
      <SignedIn>
        <Shell />
      </SignedIn>
    </>
  );
}

function Shell() {
  const { getToken } = useAuth();
  const [screen, setScreen] = useState<Screen>("connect");
  const [me, setMe] = useState<Me | null>(null);

  useTokenSource(() => getToken());

  useEffect(() => {
    void api.get<Me>("/me").then(setMe).catch(() => setMe(null));
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
                background: screen === item.id ? "var(--surface-1)" : "transparent",
                color: screen === item.id ? "var(--text-primary)" : "var(--text-secondary)",
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
        <UserButton />
      </header>

      {me?.background_jobs_paused && (
        <p
          role="alert"
          className="card"
          style={{ color: "var(--status-critical)", fontSize: 13.5, marginBottom: 16 }}
        >
          <span aria-hidden="true">⚠</span> Background work is paused:{" "}
          {me.paused_reason}. Your reports will go out of date until this is
          fixed on the “Your model” screen.
        </p>
      )}

      <main>
        {screen === "connect" && <Connect />}
        {screen === "clarify" && <Clarify />}
        {screen === "strengths" && <Strengths />}
        {screen === "roles" && <Roles />}
        {screen === "settings" && <AiSettings />}
      </main>
    </div>
  );
}
