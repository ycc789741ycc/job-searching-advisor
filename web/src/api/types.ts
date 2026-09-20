/** Response shapes, mirroring the API's own models. */

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
  clusters?: number;
  rate_is_published?: boolean;
}

export interface Subscription {
  company_id: string;
  company_name: string;
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
