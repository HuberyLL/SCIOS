// ---------------------------------------------------------------------------
// Exploration domain — mirrors backend/src/agents/exploration/schemas.py
// ---------------------------------------------------------------------------

export interface CoreConcept {
  term: string;
  explanation: string;
}

export interface ScholarProfile {
  name: string;
  affiliation: string;
  representative_works: string[];
  contribution_summary: string;
}

export interface RecommendedPaper {
  title: string;
  authors: string[];
  year: number;
  venue: string;
  citation_count: number;
  summary: string;
  url: string;
}

export interface TrendsAndChallenges {
  recent_progress: string;
  emerging_trends: string[];
  open_challenges: string[];
  future_directions: string;
}

export interface ExplorationReport {
  topic: string;
  core_concepts: CoreConcept[];
  key_scholars: ScholarProfile[];
  must_read_papers: RecommendedPaper[];
  trends_and_challenges: TrendsAndChallenges;
  sources: string[];
}

// ---------------------------------------------------------------------------
// Monitoring domain — mirrors backend/src/agents/monitoring/schemas.py
// ---------------------------------------------------------------------------

export interface HotPaper {
  title: string;
  authors: string[];
  year: number;
  url: string;
  citation_count: number;
  relevance_reason: string;
}

export interface DailyBrief {
  topic: string;
  since_date: string;
  new_hot_papers: HotPaper[];
  trend_summary: string;
  sources: string[];
}

// ---------------------------------------------------------------------------
// API envelope — mirrors backend's standard { data, meta, error } wrapper
// ---------------------------------------------------------------------------

export interface ApiResponse<T> {
  data: T;
  meta: Record<string, unknown>;
  error: string | null;
}

// ---------------------------------------------------------------------------
// Exploration task status
// ---------------------------------------------------------------------------

export type TaskStatus = "pending" | "running" | "completed" | "failed";

export interface TaskStatusData {
  task_id: string;
  status: TaskStatus;
  progress_message: string;
  result: ExplorationReport | null;
}

// ---------------------------------------------------------------------------
// Monitoring task & brief (API-level shapes)
// ---------------------------------------------------------------------------

export interface MonitorTaskData {
  id: string;
  topic: string;
  frequency: "daily" | "weekly";
  is_active: boolean;
  notify_email: string | null;
  last_run_at: string | null;
  created_at: string;
}

export interface CreateMonitorRequest {
  topic: string;
  frequency: "daily" | "weekly";
  notify_email?: string | null;
}

export interface BriefData {
  id: string;
  task_id: string;
  brief_content: DailyBrief;
  created_at: string;
}

// ---------------------------------------------------------------------------
// SSE event discriminated union — mirrors backend SSE `data:` payloads
// ---------------------------------------------------------------------------

export type SSEEvent =
  | { type: "progress"; message: string }
  | { type: "status"; status: string }
  | { type: "complete"; status: "completed"; result?: ExplorationReport }
  | { type: "error"; status: "failed"; message?: string }
  | { type: "timeout"; message: string };
