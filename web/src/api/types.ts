/**
 * Response shapes.
 *
 * `schema.d.ts` beside this file is generated from the API's OpenAPI document
 * by `make gen-client`, and CI fails if it drifts — that is what guards the
 * contract. These hand-written types are the narrow, useful view of it:
 * FastAPI infers `Record<string, unknown>` for the endpoints that return plain
 * dicts, which is true but useless at a call site.
 */

export interface Me {
  id: string;
  email: string | null;
  background_jobs_paused: boolean;
  paused_reason: string | null;
}

export interface Credential {
  provider: string;
  model: string;
  base_url: string | null;
  last_four: string;
  status: string;
  last_error: string | null;
}

export interface Budget {
  monthly_cap_usd: string;
  spent_this_month_usd: string;
  remaining_usd: string;
}

export interface Connection {
  kind: string;
  connected: boolean;
  account: string | null;
  status: string;
  last_synced_at: string | null;
  last_error: string | null;
  scopes: string[];
}

export interface ResumeFile {
  id: string;
  filename: string;
  status: string;
  parse_error: string | null;
  uploaded_at: string;
}

export interface Dimension {
  key: string;
  name: string;
  short_name: string;
  score: number;
  confidence: number;
  read: string;
  evidence_ids: string[];
}

export interface Assessment {
  id: string;
  profile_version: number;
  model_id: string;
  template_version: string;
  created_at: string;
  dimensions: Dimension[];
}

export interface Question {
  id: string;
  dimension_key: string;
  text: string;
  why: string;
  options: string[];
  answer: string | null;
}

export interface SalaryBand {
  low: number;
  mid: number;
  high: number;
  currency: string;
  sample_size: number;
  is_confident: boolean;
}

export interface Role {
  id: string;
  name: string;
  hiring_bar: number;
  bar_basis: string;
  bar_confidence: number;
  bar_reasoning: string | null;
  opening_count: number;
  salary_bands: Record<string, SalaryBand>;
  is_coherent: boolean;
  requirements: { statement: string; weight: number; expected_level: string }[];
}

export interface Fit {
  role_id: string | null;
  private_posting_id: string | null;
  score: number;
  reasoning: string;
  gaps: {
    dimension_key: string;
    user_score: number;
    target_score: number;
    delta: number;
  }[];
  uncovered: { statement: string; weight: number }[];
  model_id: string;
  computed_at: string;
}

export interface CostEstimate {
  cost_usd: string;
  model_id: string | null;
  input_tokens?: number;
  max_clusters?: number;
  /** The k this estimate was priced for (ADR 0003). */
  role_count?: number;
  rate_is_published?: boolean;
}

/** An opening inside one of the user's roles, ranked by that role's fit. */
export interface MatchedPosting {
  posting_id: string;
  role_id: string;
  role_name: string;
  title: string;
  company_name: string;
  location: string | null;
  url: string | null;
  salary: { min: number; max: number; currency: string } | null;
  fit: number | null;
  fit_basis: "role";
  subscription_id: string | null;
  source_kind: string | null;
}

export interface RoleMapSettings {
  role_count: number;
}

/** A watch on one role at one company (domain decision 19). */
export interface Subscription {
  id: string;
  company_id: string;
  company_name: string;
  role_title: string;
  role_id: string | null;
  url: string | null;
  coverage: string;
  last_refreshed_at: string | null;
}

export interface Evidence {
  id: string;
  source: string;
  reference: string;
  fact: string;
  observed_on: string | null;
  confidence: number;
}

export type TargetKind = "matchedPosting" | "subscription" | "privatePosting";

/** What a gap plan or résumé can aim at (domain decision 16). */
export interface TargetOption {
  kind: TargetKind;
  id: string;
  title: string;
  role_name: string | null;
  role_id: string | null;
  company_name: string;
  label: string;
  fit: number | null;
  salary: { min: number; max: number; currency: string } | null;
  /** atsBoard / jsonLd / publicApi, "watchlist" or "pasted". */
  source_kind: string | null;
  url: string | null;
  subscription_id: string | null;
}

export type PlanStatus = "drafting" | "ready" | "failed";

export interface PlanSummary {
  id: string;
  target: { kind: TargetKind; id: string };
  label: string;
  version: number;
  status: PlanStatus;
  error: { code: string; message: string } | null;
  model_id: string | null;
  created_at: string;
  drafted_at: string | null;
  progress: number;
}

export interface PlanGap {
  key: string;
  kind: "dimension" | "uncovered";
  name: string;
  user_score: number | null;
  target_score: number | null;
  lift: number;
  why: string;
  evidence: { id: string; reference: string; fact: string }[];
}

export interface PlanTask {
  id: string;
  text: string;
  due: string;
  closes: string[];
  done: boolean;
  /** Finished as a matching task in another plan; it counts here too. */
  done_elsewhere: boolean;
}

export interface Plan extends PlanSummary {
  template_version: string | null;
  snapshot: {
    title: string;
    company: string;
    role_name: string | null;
    fit: number | null;
    basis: "role" | "posting";
    requirements: { statement: string; expected_level: string }[];
    taken_at: string;
  } | null;
  gaps: PlanGap[];
  milestones: {
    id: string;
    title: string;
    window: string;
    outcome: string;
    tasks: PlanTask[];
  }[];
  projects: { name: string; note: string; closes: string[] }[];
  stepping_stones: {
    role_id: string;
    name: string;
    fit: number;
    openings: number;
  }[];
  versions: PlanSummary[];
}

export interface PlanEstimate extends CostEstimate {
  /** The pasted JD still has to be read and scored; that is included. */
  includes_scoring?: boolean;
}

export type ResumeTemplate = "warm" | "plain" | "brief";

export interface ResumeOptions {
  metrics: boolean;
  reorder: boolean;
  trim: boolean;
}

export interface ResumeBullet {
  text: string;
  evidence_ids: string[];
  /** "written" by the model (always cited) or "yours" (typed by the user). */
  origin: "written" | "yours";
  /** The Target requirement this line answers, if any. */
  answers: string | null;
}

export interface ResumeContent {
  name: string;
  headline: string;
  contact: string;
  summary: string;
  experience: {
    title: string;
    org: string;
    when: string;
    bullets: ResumeBullet[];
  }[];
  skills: string[];
}

export interface ResumeSummary {
  id: string;
  target: { kind: TargetKind; id: string };
  label: string;
  status: PlanStatus;
  error: { code: string; message: string } | null;
  latest_version: number | null;
  created_at: string;
  updated_at: string;
}

export interface ResumeVersion {
  id: string;
  number: number;
  label: string;
  source: "generated" | "manual" | "chat";
  model_id: string | null;
  created_at: string;
}

export interface TailoredResume extends ResumeSummary {
  template: ResumeTemplate;
  options: ResumeOptions;
  snapshot: {
    title: string;
    company: string;
    role_name: string | null;
    fit: number | null;
    basis: "role" | "posting";
  } | null;
  coverage: {
    requirement: string;
    verdict: "covered" | "partial" | "gap";
    evidence: { id: string; reference: string; fact: string }[];
  }[];
  version: ResumeVersion | null;
  content: ResumeContent | null;
  evidence: Record<string, { reference: string; fact: string }>;
  versions: ResumeVersion[];
  revisions: {
    id: string;
    request: string;
    reply: string;
    has_proposal: boolean;
    applied_version_id: string | null;
    created_at: string;
  }[];
}

export interface ResumeExport {
  id: string;
  version_id: string;
  template: ResumeTemplate;
  status: "rendering" | "ready" | "failed";
  error: { code: string; message: string } | null;
  download_url: string | null;
}
