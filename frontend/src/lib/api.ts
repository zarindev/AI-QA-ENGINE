// Typed client for the local QA Pilot API (same origin in production, proxied by Vite in development).

export type Severity = "critical" | "major" | "minor" | "trivial";
export type RunStatus = "pending" | "running" | "completed" | "failed" | "interrupted" | "cancelled";
export type StageStatus = "pending" | "running" | "done" | "skipped" | "failed";

export interface Health {
  version: string;
  api_key: boolean;
  api_key_hint: string;
  chrome: boolean;
  model: string;
  workspace: string;
  platform: string;
}

export interface Role {
  name: string;
  login_strategy: "credentials" | "manual_session" | "none";
  login_url: string;
}

export interface RunSummary {
  id: string;
  mode: "safe" | "full";
  status: RunStatus;
  stage: string;
  started_at: string | null;
  finished_at: string | null;
  pages: number;
  findings: number;
  bugs: number;
  quality_score: number | null;
  domain: string;
  cost_usd: number;
  running?: boolean;
}

export interface Project {
  slug: string;
  name: string;
  url: string;
  environment: "production" | "staging" | "test";
  authorized_by: string;
  authorized_at: string;
  roles: Role[];
  scope: { max_pages: number; max_depth: number; include_patterns: string[]; exclude_patterns: string[] };
  privacy_blur: boolean | null;
  latest_run: RunSummary | null;
  runs: number;
  running: boolean;
}

export interface StageState {
  status: StageStatus;
  progress: number;
  message: string;
  started_at: string | null;
  finished_at: string | null;
}

export interface Run {
  id: string;
  project_slug: string;
  mode: "safe" | "full";
  status: RunStatus;
  stage: string;
  stages: Record<string, StageState>;
  progress: number;
  message: string;
  started_at: string | null;
  finished_at: string | null;
  token_usage: { input_tokens: number; output_tokens: number; requests: number; cost_usd: number };
  error: string;
  running?: boolean;
  available?: Record<string, boolean>;
}

export interface PageSummary {
  id: string;
  role: string;
  url: string;
  url_template: string;
  title: string;
  status_code: number | null;
  load_time_ms: number | null;
  screenshot: string;
  thumbnail: string;
  headings: string[];
  forms: { purpose: string; field_indices: number[] }[];
  tables: { headers: string[]; row_count: number }[];
  console: { level: string; message: string }[];
  failed_requests: { url: string; status: number | null; error: string }[];
  is_login_page: boolean;
  discovered_via: string;
  element_count: number;
}

export interface PagesResponse {
  roles: { role: string; login_ok: boolean | null; login_message: string; pages: number; blocked_actions: number }[];
  blocked_actions: { role: string; page: string; action: string; target: string; reason: string }[];
  errors: { role: string; url: string; error: string }[];
  pages: PageSummary[];
}

export interface Finding {
  id: string;
  check: string;
  severity: Severity;
  title: string;
  detail: string;
  page_url: string;
  page_id: string;
  role: string;
  evidence: string[];
  data: { occurrences?: number; pages?: { url: string; role: string; page_id: string }[] } & Record<string, unknown>;
}

export interface EntityField {
  name: string;
  type: string;
  required: boolean;
  validation: string;
}

export interface SiteProfile {
  domain: string;
  sub_type: string;
  confidence: number;
  summary: string;
  method: "ai" | "heuristic";
  domain_scores: Record<string, number>;
  roles: string[];
  role_details: { name: string; description: string; observed: boolean }[];
  modules: string[];
  features: { id: string; name: string; module: string; description: string; roles: string[]; pages: string[] }[];
  entities: { name: string; fields: EntityField[]; relations: string[]; pages: string[]; operations: string[] }[];
  evidence: { claim: string; source: string; weight: number }[];
  domain_pack: string;
}

export interface FlowNode {
  id: string;
  type: string;
  position: { x: number; y: number };
  data: Record<string, unknown> & { label: string; kind: string };
}

export interface FlowGraph {
  nodes: FlowNode[];
  edges: { id: string; source: string; target: string; label: string }[];
  stats: Record<string, number>;
}

export type ReviewStatus = "proposed" | "confirmed" | "edited" | "rejected";

export interface BusinessRule {
  id: string;
  statement: string;
  condition: string;
  category: string;
  entity: string;
  source: string;
  confidence: number;
  status: ReviewStatus;
  notes: string;
}

export interface UserStory {
  id: string;
  role: string;
  feature: string;
  module: string;
  story: string;
  acceptance_criteria: string[];
  status: ReviewStatus;
}

export interface Workflow {
  id: string;
  name: string;
  entity: string;
  description: string;
  roles: string[];
  steps: { order: number; action: string; role: string; page: string; state_after: string }[];
  states: string[];
  transitions: { from_state: string; to_state: string; action: string; allowed: boolean; role: string }[];
}

export interface Requirements {
  method: "ai" | "heuristic";
  stories: UserStory[];
  workflows: Workflow[];
  rules: BusinessRule[];
}

export interface TestStep {
  order: number;
  action: string;
  data: string;
  expected: string;
}

export interface TestCase {
  id: string;
  title: string;
  module: string;
  technique: string;
  type: string;
  priority: "P1" | "P2" | "P3" | "P4";
  role: string;
  preconditions: string[];
  test_data: Record<string, unknown>;
  steps: TestStep[];
  expected_result: string;
  links: Record<string, string[]>;
  status: "draft" | "approved" | "skipped";
  source: "generated" | "ai" | "user" | "plain_english";
  requires_full_mode: boolean;
  viewports: string[];
  edited: boolean;
}

export interface Estimate {
  cases: number;
  steps: number;
  input_tokens: number;
  output_tokens: number;
  cost_usd: number;
  minutes: number;
  blocked_in_safe_mode: number;
  model: string;
  mode: "safe" | "full";
}

export type ExportKind =
  | "requirements" | "testcases_xlsx" | "gherkin_zip" | "qa_report_pdf" | "qa_xlsx" | "bugs_pdf" | "bug_pdf"
  | "jira_csv" | "trello_csv" | "traceability_csv" | "pytest_zip";

export interface ExportFile {
  kind: string;
  path: string;
  size: number;
  modified: number;
}

export type ResultKind = "pass" | "fail" | "blocked" | "error";

export interface StepResult {
  order: number;
  action: string;
  target: string;
  input: string;
  observation: string;
  result: ResultKind;
  url: string;
  screenshot_before: string;
  screenshot_after: string;
  duration_ms: number;
  blocked_reason: string;
}

export interface Execution {
  test_case_id: string;
  attempt: number;
  result: ResultKind;
  reason: string;
  expected: string;
  actual: string;
  confidence: number;
  method: "agent" | "replay" | "replay_healed" | "rule";
  role: string;
  viewport: string;
  started_at: string;
  finished_at: string | null;
  steps: StepResult[];
  failure_step: number | null;
  auto_findings: { check: string; severity: Severity; title: string; detail: string; url: string; step: number | null }[];
  video: string;
  console_log: string;
  network_log: string;
  token_usage: { cost_usd: number; requests: number };
  rule_checks: { rule_id: string; expression: string; values: Record<string, number>; holds: boolean | null; explanation: string; error: string }[];
}

export type Viewport = "desktop" | "tablet" | "mobile";

export interface SubScore { key: string; label: string; score: number | null; passed: number; executed: number; bugs: number; note: string }
export interface Quality { score: number | null; grade: string; sub_scores: SubScore[]; formula: string }
export interface HeatCell { module: string; technique: string; state: "pass" | "fail" | "warn" | "untested"; total: number; passed: number; failed: number; other: number; cases: string[] }
export interface Heatmap { modules: string[]; techniques: string[]; cells: HeatCell[] }
export interface MatrixCell { role: string; page: string; expected: "allow" | "deny" | "unknown"; observed: "allow" | "deny" | "untested"; hole: boolean; source: string; evidence: string }
export interface PermissionMatrix { roles: string[]; pages: string[]; cells: MatrixCell[]; holes: number }
export interface ComparedBug { key: string; title: string; severity: Severity; status: "new" | "fixed" | "reappeared" | "still_open"; current_id: string; base_id: string }
export interface Comparison { base_run: string; current_run: string; counts: Record<ComparedBug["status"], number>; bugs: ComparedBug[] }

export interface TestRunResult {
  test_case_id: string;
  title: string;
  module: string;
  technique: string;
  priority: "P1" | "P2" | "P3" | "P4";
  role: string;
  result: ResultKind;
  reproducibility: string;
  flaky: boolean;
  reason: string;
  method: string;
  viewport: string;
  duration_ms: number;
  cost_usd: number;
  bug_ids: string[];
}

export type BugStatus = "new" | "needs_review" | "confirmed" | "rejected" | "fixed";

export interface Bug {
  id: string;
  title: string;
  summary: string;
  module: string;
  severity: Severity;
  severity_reason: string;
  priority: "P1" | "P2" | "P3" | "P4";
  confidence: number;
  environment: { browser: string; os: string; viewport: string; url: string; role: string; date_time: string };
  preconditions: string[];
  steps_to_reproduce: string[];
  expected: string;
  actual: string;
  evidence: string[];
  reproducibility: string;
  links: Record<string, string[]>;
  status: BugStatus;
  category: string;
  test_case_ids: string[];
  screenshot: string;
  annotated_screenshot: string;
  clip: string;
  video: string;
  console: string[];
  network: string[];
  source: "test" | "automatic_check";
}

export class ApiError extends Error {
  constructor(
    public status: number,
    message: string,
  ) {
    super(message);
  }
}

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const res = await fetch(path, {
    ...init,
    headers: { "Content-Type": "application/json", ...(init?.headers ?? {}) },
  });
  if (res.status === 204) return undefined as T;
  const text = await res.text();
  const body = text ? JSON.parse(text) : undefined;
  if (!res.ok) {
    const detail = body?.detail;
    const message = Array.isArray(detail)
      ? detail.map((d: { msg: string }) => d.msg).join("; ")
      : detail || `Request failed (${res.status})`;
    throw new ApiError(res.status, message);
  }
  return body as T;
}

export const api = {
  health: () => request<Health>("/api/health"),
  saveApiKey: (key: string, workspace_id = "") =>
    request<{ ok: boolean; message: string }>("/api/settings/api-key", {
      method: "POST",
      body: JSON.stringify({ key, workspace_id }),
    }),
  settings: () => request<Record<string, Record<string, unknown>>>("/api/settings"),
  saveSettings: (body: Record<string, unknown>) =>
    request<Record<string, Record<string, unknown>>>("/api/settings", { method: "PUT", body: JSON.stringify(body) }),
  resetSettings: () => request<Record<string, Record<string, unknown>>>("/api/settings", { method: "DELETE" }),
  openWorkspace: () => request<{ opened: string }>("/api/settings/open-workspace", { method: "POST" }),
  projects: () => request<Project[]>("/api/projects"),
  project: (slug: string) => request<Project>(`/api/projects/${slug}`),
  createProject: (body: unknown) => request<Project>("/api/projects", { method: "POST", body: JSON.stringify(body) }),
  deleteProject: (slug: string) => request<void>(`/api/projects/${slug}`, { method: "DELETE" }),
  startManualLogin: (slug: string, role: string) =>
    request<{ message: string }>(`/api/projects/${slug}/roles/${role}/manual-session`, { method: "POST" }),
  finishManualLogin: (slug: string, role: string) =>
    request<{ status: string }>(`/api/projects/${slug}/roles/${role}/manual-session/finish`, { method: "POST" }),
  runs: (slug: string) => request<RunSummary[]>(`/api/projects/${slug}/runs`),
  startRun: (slug: string, body: { mode: "safe" | "full"; confirm_full_mode?: boolean }) =>
    request<Run>(`/api/projects/${slug}/runs`, { method: "POST", body: JSON.stringify(body) }),
  run: (slug: string, id: string) => request<Run>(`/api/projects/${slug}/runs/${id}`),
  cancelRun: (slug: string, id: string) => request<void>(`/api/projects/${slug}/runs/${id}/cancel`, { method: "POST" }),
  resumeRun: (slug: string, id: string) => request<Run>(`/api/projects/${slug}/runs/${id}/resume`, { method: "POST" }),
  pages: (slug: string, id: string) => request<PagesResponse>(`/api/projects/${slug}/runs/${id}/pages`),
  findings: (slug: string, id: string) =>
    request<{ findings: Finding[] }>(`/api/projects/${slug}/runs/${id}/findings`),
  profile: (slug: string, id: string) => request<SiteProfile>(`/api/projects/${slug}/runs/${id}/profile`),
  model: (slug: string, id: string, kinds: string[]) =>
    request<FlowGraph>(`/api/projects/${slug}/runs/${id}/model?kinds=${kinds.join(",")}`),
  requirements: (slug: string, id: string) => request<Requirements>(`/api/projects/${slug}/runs/${id}/requirements`),
  updateRule: (slug: string, id: string, ruleId: string, body: Partial<Pick<BusinessRule, "status" | "statement" | "condition" | "notes">>) =>
    request<BusinessRule>(`/api/projects/${slug}/runs/${id}/requirements/rules/${ruleId}`, { method: "PATCH", body: JSON.stringify(body) }),
  bulkRules: (slug: string, id: string, ids: string[], status: "confirmed" | "rejected" | "proposed") =>
    request<{ updated: number }>(`/api/projects/${slug}/runs/${id}/requirements/rules/bulk`, { method: "POST", body: JSON.stringify({ ids, status }) }),
  testcases: (slug: string, id: string) => request<{ cases: TestCase[] }>(`/api/projects/${slug}/runs/${id}/testcases`),
  updateCase: (slug: string, id: string, caseId: string, body: Record<string, unknown>) =>
    request<TestCase>(`/api/projects/${slug}/runs/${id}/testcases/${caseId}`, { method: "PATCH", body: JSON.stringify(body) }),
  bulkCases: (slug: string, id: string, ids: string[], status: TestCase["status"]) =>
    request<{ updated: number }>(`/api/projects/${slug}/runs/${id}/testcases/bulk`, { method: "POST", body: JSON.stringify({ ids, status }) }),
  deleteCase: (slug: string, id: string, caseId: string) =>
    request<void>(`/api/projects/${slug}/runs/${id}/testcases/${caseId}`, { method: "DELETE" }),
  plainEnglish: (slug: string, id: string, text: string, role = "") =>
    request<TestCase>(`/api/projects/${slug}/runs/${id}/testcases/plain-english`, { method: "POST", body: JSON.stringify({ text, role }) }),
  regenerate: (slug: string, id: string) =>
    request<{ status: string }>(`/api/projects/${slug}/runs/${id}/testcases/regenerate`, { method: "POST" }),
  estimate: (slug: string, id: string, status = "approved") =>
    request<Estimate>(`/api/projects/${slug}/runs/${id}/testcases/estimate?status=${status}`),
  exports: (slug: string, id: string) => request<ExportFile[]>(`/api/projects/${slug}/runs/${id}/exports`),
  createExport: (slug: string, id: string, kind: ExportKind, bugId?: string) =>
    request<{ files: string[] }>(`/api/projects/${slug}/runs/${id}/exports/${kind}${bugId ? `?bug_id=${bugId}` : ""}`, { method: "POST" }),
  execute: (slug: string, id: string, caseIds?: string[], viewports: Viewport[] = ["desktop"]) =>
    request<{ status: string; cases: number; agent_cases: number; ai: boolean; mode: string }>(
      `/api/projects/${slug}/runs/${id}/execute`, { method: "POST", body: JSON.stringify({ case_ids: caseIds ?? null, viewports }) }),
  quality: (slug: string, id: string) =>
    request<{ quality: Quality; heatmap: Heatmap | null }>(`/api/projects/${slug}/runs/${id}/quality`),
  permissions: (slug: string, id: string) => request<PermissionMatrix>(`/api/projects/${slug}/runs/${id}/permissions`),
  compare: (slug: string, id: string, base?: string) =>
    request<{ available: string[]; comparison: Comparison | null }>(`/api/projects/${slug}/runs/${id}/compare${base ? `?base=${base}` : ""}`),
  updateProject: (slug: string, body: { privacy_blur?: "auto" | "on" | "off"; name?: string }) =>
    request<Project>(`/api/projects/${slug}`, { method: "PATCH", body: JSON.stringify(body) }),
  results: (slug: string, id: string) =>
    request<{ results: TestRunResult[]; mode: string; started_at: string; finished_at: string | null }>(`/api/projects/${slug}/runs/${id}/results`),
  executions: (slug: string, id: string, caseId: string) =>
    request<{ test_case_id: string; attempts: Execution[] }>(`/api/projects/${slug}/runs/${id}/executions/${caseId}`),
  bugs: (slug: string, id: string) => request<{ bugs: Bug[] }>(`/api/projects/${slug}/runs/${id}/bugs`),
  updateBug: (slug: string, id: string, bugId: string, body: Partial<Pick<Bug, "status" | "severity" | "priority">>) =>
    request<Bug>(`/api/projects/${slug}/runs/${id}/bugs/${bugId}`, { method: "PATCH", body: JSON.stringify(body) }),
  replayBug: (slug: string, id: string, bugId: string) =>
    request<{ message: string }>(`/api/projects/${slug}/runs/${id}/bugs/${bugId}/replay`, { method: "POST" }),
  startDemo: () => request<{ project: string; run: string }>("/api/demo/start", { method: "POST" }),
};

export const fileUrl = (slug: string, runId: string, path: string) =>
  `/api/projects/${slug}/runs/${runId}/files/${path}`;
