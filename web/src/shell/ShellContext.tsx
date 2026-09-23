import { createContext, useContext } from "react";
import type { Credential, Me } from "../api/types";
import type { Screen } from "./navigation";

/** What the sidebar and header show about the account, loaded once. */
export interface ShellStatus {
  me: Me | null;
  credential: Credential | null;
  /** Follow-up questions still waiting for an answer. */
  openQuestions: number;
  /** Mean dimension confidence of the latest analysis, 0–100, or null. */
  confidence: number | null;
}

export interface Shell {
  status: ShellStatus;
  navigate: (screen: Screen) => void;
  /** Re-reads the status, after something a screen did changed it. */
  refresh: () => Promise<void>;
  /** The header's target chip: what the plan or résumé is aimed at. */
  target: string | null;
  setTarget: (label: string | null) => void;
}

const EMPTY: ShellStatus = {
  me: null,
  credential: null,
  openQuestions: 0,
  confidence: null,
};

export const ShellContext = createContext<Shell>({
  status: EMPTY,
  navigate: () => {},
  refresh: async () => {},
  target: null,
  setTarget: () => {},
});

export function useShell(): Shell {
  return useContext(ShellContext);
}

/** The model a screen names in its copy: the configured one, or a stand-in. */
export function modelName(credential: Credential | null): string {
  return credential?.model ?? "your model";
}
