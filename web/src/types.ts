export interface TaskDefinition {
  task_id: string;
  track: string;
  title?: string;
  title_en?: string;
  title_zh?: string;
  credits_budget?: number;
  timeout_sec?: number;
}

export interface L3LayoutObstacle {
  id: string;
  kind: string;
  x0: number;
  y0: number;
  x1: number;
  y1: number;
  clearance: number;
}

export interface L3LayoutUnit {
  id: string;
  kind: "liquid-rack" | "air-rack" | "cdu" | string;
  row: number;
  x0: number;
  y0: number;
  x1: number;
  y1: number;
  cu: number | null;
}

export interface L3LayoutSpine {
  id: string;
  x: number;
  y: number;
  w: number;
  d: number;
  collided: boolean;
}

export interface L3LayoutBufferTank {
  x: number;
  y: number;
  side: number;
  m3: number;
  collided: boolean;
}

export interface L3LayoutSnapshot {
  hall_length_m: number;
  hall_width_m: number;
  copper_max_reach_m: number;
  row_count: number;
  cold_aisle_m: number;
  hot_aisle_m: number;
  cdu_topology: string;
  cdu_count: number;
  tcs_header_dn_mm: number;
  busway_rating_a: number;
  copper_ratio: number;
  obstacles: L3LayoutObstacle[];
  units: L3LayoutUnit[];
  spines: L3LayoutSpine[];
  buffer_tank: L3LayoutBufferTank;
}

export interface TaskMeta {
  task_id: string;
  track: string;
  title_en: string;
  title_zh: string;
  category?: string;
  credits_budget?: number;
  timeout_sec?: number;
  instruction_md?: string;
  instruction_md_en?: string;
  instruction_md_zh?: string;
  starter_files?: Record<string, string>;
  oracle_layout?: L3LayoutSnapshot | null;
  schema_json?: string;
  [key: string]: unknown;
}

export interface TrialTaskResult {
  score_100: number;
  soft_quality_score: number;
  signoff_passed: boolean;
  run_status: string;
  outcome_state?: string;
  failure_stage?: string | null;
  failure_reasons?: string[];
  regret_pct?: number | null;
  credits_used: number;
  credits_budget: number;
  elapsed_sec?: number | null;
  worst_margin?: string;
  reward?: number;
  [key: string]: unknown;
}

export interface TrialRun {
  total_score_800: number;
  passed_count: number;
  elapsed_sec_sum: number;
  tasks: Record<string, TrialTaskResult>;
}

export interface BenchmarkEntry {
  slug: string;
  model: string;
  model_name: string;
  agent_harness: string;
  is_reference?: boolean;
  is_outcome_col?: boolean;
  n_trials: number;
  mean_total_800: number;
  std_total_800: number;
  pass_at_1_pct: number;
  pass_at_1_ci95_pct: number;
  pass_at_k_pct: number;
  pass_pow_k_pct: number;
  mean_soft_100: number;
  mean_soft_score?: number;
  mean_regret_pct?: number | null;
  mean_credits_pct: number;
  mean_task_sec: number;
  total_elapsed_sec?: number;
  total_score?: number;
  elapsed_sec?: number;
  run_status?: string;
  error_runs: number;
  timeout_runs: number;
  passed_trials?: number;
  timeout_passed_trials?: number;
  timeout_trials?: number;
  error_trials?: number;
  failed_trials?: number;
  trials: Record<string, TrialRun>;
  [key: string]: any;
}

export interface VersionReport {
  version: string;
  label?: string;
  max_score: number;
  canary_guid?: string;
  harbor_verification?: {
    oracle_passed?: number;
    nop_zero?: number;
    [key: string]: unknown;
  };
  tasks: TaskDefinition[];
  entries: BenchmarkEntry[];
  [key: string]: unknown;
}

export interface BenchmarkRelease {
  version: string;
  name?: string;
  title_en?: string;
  title_zh?: string;
  date: string;
  status: string;
  tasks_count: number;
  trials_per_task?: number;
  summary_en: string;
  summary_zh: string;
  blog_slug?: string;
}

export interface NewsPost {
  slug: string;
  date: string;
  author: string;
  title_en: string;
  title_zh: string;
  summary_en: string;
  summary_zh: string;
  body_en: string;
  body_zh: string;
}

export interface ContributorGroup {
  role_en: string;
  role_zh: string;
  members: Array<{ name: string; org?: string; url?: string }>;
}

export interface ContributorsVersion {
  ack_en?: string;
  ack_zh?: string;
  groups: ContributorGroup[];
}

export interface TrialDetail {
  verifier?: Record<string, string>;
  submissions?: Record<string, string>;
  l3_layout?: L3LayoutSnapshot | null;
  agent_log?: string;
  prompt?: string;
  config?: Record<string, unknown>;
  [key: string]: unknown;
}

export interface DashboardPayload {
  versions: Record<string, VersionReport>;
  task_meta: Record<string, TaskMeta>;
  benchmarks: BenchmarkRelease[];
  news: NewsPost[];
  contributors: Record<string, ContributorsVersion>;
  trial_details?: Record<string, TrialDetail>;
}

export interface FiltersState {
  tracks: string[];
  agents: string[];
  models: string[];
  showRef: boolean;
  hideHighError: boolean;
  scoreRange: [number, number] | null;
  pass1Range: [number, number] | null;
  creditsRange: [number, number] | null;
  timeRange: [number, number] | null;
  [key: string]: any;
}

export interface AppState {
  version: string;
  prevVersion: string | null;
  verAnimPending: boolean;
  viewFadePending: boolean;
  view: string;
  sortCol: string;
  sortDir: "asc" | "desc";
  columns: Record<string, boolean>;
  filters: FiltersState;
  paretoX: string;
  paretoY: string;
  paretoOpts: Record<string, boolean>;
  waffleDim1: string;
  waffleDim2: string;
  waffleOpts: Record<string, boolean>;
  waffleExpand: boolean;
  openPopover: string | null;
  activeFilterCat: string | null;
  mobileNavOpen: boolean;
  rowTab: string;
  rowGroupBy: string;
  trialFilter: string;
  trialSearch: string;
  trialTab: string;
  selectedVerifierFile: string;
  selectedSubmissionFile: string;
  selectedTaskFile: string;
  taskDetailTab: string;
  runPkgTab: string;
  tasksTrackFilter: string;
  contribVersion: string;
  theme: string;
  lang: string;
}

export interface CustomSelectOption {
  value: string;
  label: string;
}

export interface CustomSelectProps {
  id: string;
  value: string;
  options: CustomSelectOption[];
  align?: "left" | "right";
  small?: boolean;
  width?: number | null;
  autoWidth?: boolean;
  ariaLabel?: string;
}

export type Route =
  | { page: "home"; query: URLSearchParams }
  | { page: "run"; query: URLSearchParams }
  | { page: "tasks"; query: URLSearchParams }
  | { page: "task_detail"; taskId: string; query: URLSearchParams }
  | { page: "benchmarks"; query: URLSearchParams }
  | { page: "news"; query: URLSearchParams }
  | { page: "news_detail"; slug: string; query: URLSearchParams }
  | { page: "community"; query: URLSearchParams }
  | { page: "contributors"; query: URLSearchParams }
  | { page: "row"; slug: string; query: URLSearchParams }
  | { page: "trial"; slug: string; trialKey: string; query: URLSearchParams };

declare global {
  interface Window {
    __activeViewerContent?: string;
  }
}
