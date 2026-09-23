import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { api } from "./api/client";
import type { Assessment, Credential, Me, Question } from "./api/types";
import { useAuth } from "./auth/AuthProvider";
import { SignInScreen } from "./auth/SignInScreen";
import { EmptyState, Loading } from "./components/ui";
import { AiSettings } from "./features/AiSettings";
import { Clarify } from "./features/Clarify";
import { Connect } from "./features/Connect";
import { GapPlan } from "./features/GapPlan";
import {
  completeCallback,
  type CallbackOutcome,
} from "./features/oauthCallback";
import { Roles } from "./features/Roles";
import { Strengths } from "./features/Strengths";
import {
  hashFor,
  metaOf,
  screenFromHash,
  type Screen,
} from "./shell/navigation";
import { PageHeader } from "./shell/PageHeader";
import {
  ShellContext,
  type Handoff,
  type ShellStatus,
} from "./shell/ShellContext";
import { Sidebar } from "./shell/Sidebar";
import { ToastProvider } from "./shell/toast";

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
  return status === "signed-in" ? (
    <ToastProvider>
      <Shell />
    </ToastProvider>
  ) : (
    <SignInScreen />
  );
}

/** What the sidebar and header need. Pieces fail independently. */
export async function loadStatus(): Promise<ShellStatus> {
  const [me, credential, questions, assessment] = await Promise.all([
    api.get<Me>("/me").catch(() => null),
    api.get<Credential | null>("/ai-credential").catch(() => null),
    api.get<Question[]>("/questions").catch(() => [] as Question[]),
    api.get<Assessment | null>("/assessments/latest").catch(() => null),
  ]);
  const dimensions = assessment?.dimensions ?? [];
  return {
    me,
    credential,
    openQuestions: questions.filter((question) => question.answer === null)
      .length,
    confidence:
      dimensions.length === 0
        ? null
        : Math.round(
            (dimensions.reduce((sum, d) => sum + d.confidence, 0) /
              dimensions.length) *
              100,
          ),
  };
}

function Shell() {
  const { email, signOut } = useAuth();
  const [screen, setScreen] = useState<Screen>(() =>
    screenFromHash(window.location.hash),
  );
  const [status, setStatus] = useState<ShellStatus>({
    me: null,
    credential: null,
    openQuestions: 0,
    confidence: null,
  });
  const [target, setTarget] = useState<string | null>(null);
  const [handoff, setHandoff] = useState<Handoff | null>(null);
  const [callback, setCallback] = useState<CallbackOutcome | null>(null);
  const handled = useRef(false);

  const navigate = useCallback((next: Screen, carried?: Handoff) => {
    setHandoff(carried ?? null);
    setScreen(next);
    if (window.location.hash !== hashFor(next)) {
      window.history.pushState(null, "", hashFor(next));
    }
  }, []);

  // Back and forward move between screens like any other page.
  useEffect(() => {
    const onHash = () => setScreen(screenFromHash(window.location.hash));
    window.addEventListener("popstate", onHash);
    window.addEventListener("hashchange", onHash);
    return () => {
      window.removeEventListener("popstate", onHash);
      window.removeEventListener("hashchange", onHash);
    };
  }, []);

  // Returning from GitHub or Jira lands on /connections/{kind}/callback.
  // Handled once per page load: the code it carries is single-use.
  useEffect(() => {
    if (handled.current) return;
    handled.current = true;
    void completeCallback(window.location, (url) =>
      window.history.replaceState(null, "", url),
    ).then((outcome) => {
      if (outcome) {
        navigate("sources");
        setCallback(outcome);
      }
    });
  }, [navigate]);

  const refresh = useCallback(async () => {
    setStatus(await loadStatus());
  }, []);

  useEffect(() => {
    void refresh();
  }, [refresh]);

  const shell = useMemo(
    () => ({ status, navigate, handoff, refresh, target, setTarget }),
    [status, navigate, handoff, refresh, target],
  );
  const me = status.me;

  return (
    <ShellContext.Provider value={shell}>
      <div className="app">
        <Sidebar current={screen} status={status} onNavigate={navigate} />
        <main className="main">
          <PageHeader
            meta={metaOf(screen)}
            status={status}
            target={target}
            email={me?.email ?? email}
            onSignOut={() => void signOut()}
          />
          <div className="page-body" key={screen}>
            {me?.background_jobs_paused && (
              <p
                role="alert"
                className="inset"
                style={{
                  color: "var(--status-critical)",
                  fontSize: 13.5,
                  fontWeight: 600,
                  marginTop: 0,
                }}
              >
                <span aria-hidden="true">⚠</span> Background work is paused:{" "}
                {me.paused_reason}. Your reports will go out of date until this
                is fixed under “AI &amp; model”.
              </p>
            )}
            {screen === "sources" && <Connect callback={callback} />}
            {screen === "questions" && <Clarify />}
            {screen === "strengths" && <Strengths />}
            {screen === "roles" && <Roles />}
            {screen === "plan" && <GapPlan />}
            {screen === "resume" && (
              <EmptyState title="Résumé writing is on its way">
                Tailoring a résumé to one role at a time arrives in the next
                release.
              </EmptyState>
            )}
            {screen === "model" && <AiSettings />}
          </div>
        </main>
      </div>
    </ShellContext.Provider>
  );
}
