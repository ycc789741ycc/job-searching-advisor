import {
  createContext,
  useCallback,
  useContext,
  useEffect,
  useMemo,
  useRef,
  useState,
  type ReactNode,
} from "react";
import { setTokenSource } from "../api/client";
import * as session from "./session";

interface AuthState {
  status: "loading" | "signed-out" | "signed-in";
  email: string | null;
  register: (email: string, password: string) => Promise<void>;
  signIn: (email: string, password: string) => Promise<void>;
  signOut: () => Promise<void>;
}

const AuthContext = createContext<AuthState | null>(null);

// Refresh this far before expiry, so a request never races the clock.
const REFRESH_MARGIN_MS = 60_000;

export function AuthProvider({ children }: { children: ReactNode }) {
  const [current, setCurrent] = useState<session.Session | null>(null);
  const [status, setStatus] = useState<AuthState["status"]>("loading");

  // Held in a ref as well as state: the token getter below must read the
  // latest value without being re-created on every render.
  const sessionRef = useRef<session.Session | null>(null);
  const inFlight = useRef<Promise<session.Session> | null>(null);

  const adopt = useCallback((next: session.Session | null) => {
    sessionRef.current = next;
    setCurrent(next);
    setStatus(next ? "signed-in" : "signed-out");
  }, []);

  /**
   * The access token for the next API call, refreshed if it is about to expire.
   *
   * Concurrent callers share one refresh: without that, a page that fires
   * several requests at once would rotate the refresh token several times and
   * trip the reuse detection, signing the user out.
   */
  const getToken = useCallback(async (): Promise<string | null> => {
    const held = sessionRef.current;
    if (held && held.expiresAt - Date.now() > REFRESH_MARGIN_MS) {
      return held.accessToken;
    }
    if (!inFlight.current) {
      inFlight.current = session.refresh().finally(() => {
        inFlight.current = null;
      });
    }
    try {
      const renewed = await inFlight.current;
      adopt(renewed);
      return renewed.accessToken;
    } catch {
      adopt(null);
      return null;
    }
  }, [adopt]);

  useEffect(() => {
    setTokenSource(getToken);
  }, [getToken]);

  // On load, try the refresh cookie: a reload should not mean signing in again.
  useEffect(() => {
    let cancelled = false;
    session
      .refresh()
      .then((renewed) => !cancelled && adopt(renewed))
      .catch(() => !cancelled && adopt(null));
    return () => {
      cancelled = true;
    };
  }, [adopt]);

  const value = useMemo<AuthState>(
    () => ({
      status,
      email: current?.email ?? null,
      register: async (email, password) =>
        adopt(await session.register(email, password)),
      signIn: async (email, password) =>
        adopt(await session.signIn(email, password)),
      signOut: async () => {
        await session.signOut().catch(() => undefined);
        adopt(null);
      },
    }),
    [status, current, adopt],
  );

  return <AuthContext.Provider value={value}>{children}</AuthContext.Provider>;
}

export function useAuth(): AuthState {
  const value = useContext(AuthContext);
  if (!value) throw new Error("useAuth must be used inside an AuthProvider");
  return value;
}
