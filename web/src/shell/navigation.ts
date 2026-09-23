/**
 * Which screen is showing, kept in the URL hash.
 *
 * The prototype's sidebar numbers the journey 01–06 and keeps the model
 * settings apart as "system configuration". The hash (`#/plan`) lets a reload
 * or a shared link land on the same screen, without a router dependency.
 */

export type Screen =
  | "sources"
  | "questions"
  | "strengths"
  | "roles"
  | "plan"
  | "resume"
  | "model";

export interface ScreenMeta {
  id: Screen;
  /** Shown before the label in the sidebar; absent for settings. */
  num?: string;
  label: string;
  /** The page heading. */
  title: string;
  kicker: string;
}

/** The numbered journey, in order. */
export const JOURNEY: readonly ScreenMeta[] = [
  {
    id: "sources",
    num: "01",
    label: "Sources",
    title: "Bring in your real work",
    kicker: "Profile · Step 1",
  },
  {
    id: "questions",
    num: "02",
    label: "Questions",
    title: "Things I need you to settle",
    kicker: "Profile · Step 2",
  },
  {
    id: "strengths",
    num: "03",
    label: "Strengths",
    title: "Where you actually stand",
    kicker: "Report",
  },
  {
    id: "roles",
    num: "04",
    label: "Role map",
    title: "The roles worth your next six months",
    kicker: "Report",
  },
  {
    id: "plan",
    num: "05",
    label: "Gap plan",
    title: "Closing the distance",
    kicker: "Plan",
  },
  {
    id: "resume",
    num: "06",
    label: "Résumé",
    title: "Written for one target at a time",
    kicker: "Output",
  },
];

export const MODEL_SCREEN: ScreenMeta = {
  id: "model",
  label: "AI & model",
  title: "Bring your own model",
  kicker: "System configuration",
};

const ALL: readonly ScreenMeta[] = [...JOURNEY, MODEL_SCREEN];

export const DEFAULT_SCREEN: Screen = "sources";

export function metaOf(screen: Screen): ScreenMeta {
  return ALL.find((item) => item.id === screen) ?? JOURNEY[0]!;
}

/** The screen a hash names, or the default for anything else. Pure. */
export function screenFromHash(hash: string): Screen {
  const id = hash.replace(/^#\/?/, "");
  return ALL.some((item) => item.id === id) ? (id as Screen) : DEFAULT_SCREEN;
}

export function hashFor(screen: Screen): string {
  return `#/${screen}`;
}
