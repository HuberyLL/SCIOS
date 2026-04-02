// ---------------------------------------------------------------------------
// Dynamic Research Landscape — mirrors backend/src/models/landscape.py
// ---------------------------------------------------------------------------

// -- TechTree ---------------------------------------------------------------

export type TechTreeNodeType = "method" | "paper" | "milestone";
export type TechTreeRelation =
  | "evolves_from"
  | "extends"
  | "alternative_to"
  | "inspires";

export interface TechTreeNode {
  node_id: string;
  label: string;
  node_type: TechTreeNodeType;
  year: number | null;
  description: string;
  representative_paper_ids: string[];
  is_new: boolean;
}

export interface TechTreeEdge {
  source: string;
  target: string;
  relation: TechTreeRelation;
  label: string;
}

export interface TechTree {
  nodes: TechTreeNode[];
  edges: TechTreeEdge[];
}

// -- CollaborationNetwork ---------------------------------------------------

export interface ScholarNode {
  scholar_id: string;
  name: string;
  affiliations: string[];
  paper_count: number;
  citation_count: number;
  h_index: number;
  top_paper_ids: string[];
  is_new: boolean;
}

export interface CollaborationEdge {
  source: string;
  target: string;
  weight: number;
  shared_paper_ids: string[];
}

export interface CollaborationNetwork {
  nodes: ScholarNode[];
  edges: CollaborationEdge[];
}

// -- ResearchGaps -----------------------------------------------------------

export type GapImpact = "high" | "medium" | "low";

export interface ResearchGap {
  gap_id: string;
  title: string;
  description: string;
  evidence_paper_ids: string[];
  potential_approaches: string[];
  impact: GapImpact;
}

export interface ResearchGaps {
  gaps: ResearchGap[];
  summary: string;
}

// -- Envelope ---------------------------------------------------------------

export interface LandscapeMeta {
  topic: string;
  generated_at: string;
  paper_count: number;
  version: number;
}

export interface PaperResult {
  paper_id: string;
  title: string;
  authors: string[];
  abstract: string;
  doi: string;
  published_date: string;
  pdf_url: string;
  url: string;
  source: string;
  categories: string[];
  citation_count: number;
}

export interface DynamicResearchLandscape {
  meta: LandscapeMeta;
  tech_tree: TechTree;
  collaboration_network: CollaborationNetwork;
  research_gaps: ResearchGaps;
  papers: PaperResult[];
  sources: string[];
}

export interface LandscapeTaskListItem {
  task_id: string;
  topic: string;
  status: TaskStatus;
  progress_message: string;
  has_result: boolean;
  created_at: string;
  updated_at: string;
}

export interface LandscapeIncrement {
  new_papers: PaperResult[];
  new_tech_nodes: TechTreeNode[];
  new_tech_edges: TechTreeEdge[];
  new_scholars: ScholarNode[];
  new_collab_edges: CollaborationEdge[];
  new_gaps: ResearchGap[];
  detected_at: string | null;
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
// Task status (shared)
// ---------------------------------------------------------------------------

export type TaskStatus = "pending" | "running" | "completed" | "failed";

export interface LandscapeTaskStatus {
  task_id: string;
  status: TaskStatus;
  progress_message: string;
  current_stage_id?: StageId | "";
  current_progress_pct?: number;
  progress_snapshot?: Record<string, LandscapeSSEEvent>;
  result: DynamicResearchLandscape | null;
}

// ---------------------------------------------------------------------------
// Pipeline stage tracking (for structured progress UI)
// ---------------------------------------------------------------------------

export type StageId =
  | "scope"
  | "retrieval"
  | "taxonomy"
  | "network"
  | "gaps"
  | "critic"
  | "assembler";

export type StageStatus = "pending" | "running" | "completed" | "failed" | "skipped";

export interface PipelineStage {
  id: StageId;
  label: string;
  index: number;
  status: StageStatus;
  messages: string[];
  elapsed_s: number;
  detail: Record<string, unknown> | null;
}

// ---------------------------------------------------------------------------
// SSE event discriminated union — mirrors backend SSE `data:` payloads
// ---------------------------------------------------------------------------

export type LandscapeSSEEvent =
  | {
      type: "progress";
      message: string;
      stage_id?: StageId;
      stage_index?: number;
      stage_total?: number;
      status?: string;
      progress_pct?: number;
      elapsed_s?: number;
      detail?: Record<string, unknown>;
      agent?: string;
    }
  | { type: "status"; status: string }
  | { type: "complete"; status: "completed"; result?: DynamicResearchLandscape }
  | { type: "error"; status: "failed"; message?: string }
  | { type: "timeout"; message: string };

// ---------------------------------------------------------------------------
// Assistant domain — mirrors backend/src/models/assistant.py + API schemas
// ---------------------------------------------------------------------------

export interface AssistantSession {
  id: string;
  title: string;
  created_at: string;
  updated_at: string;
}

export interface AssistantMessageOut {
  id: string;
  session_id: string;
  role: "system" | "user" | "assistant" | "tool";
  content: string;
  tool_calls: Record<string, unknown>[] | null;
  tool_call_id: string | null;
  created_at: string;
}

export type ToolCallStatus = "running" | "completed" | "error";

export interface ToolCallBlock {
  tool_call_id: string;
  tool_name: string;
  args: Record<string, unknown>;
  result?: string;
  status: ToolCallStatus;
}

export interface ChatMessage {
  id: string;
  role: "user" | "assistant";
  content: string;
  tool_calls: ToolCallBlock[];
  isStreaming?: boolean;
}

export type ArtifactType = "pdf" | "image" | "code" | "text" | "markdown";

export interface Artifact {
  type: ArtifactType;
  path: string;
  label: string;
}

export type AssistantWSEvent =
  | { event: "text_delta"; data: { content: string } }
  | {
      event: "tool_call_start";
      data: {
        tool_name: string;
        tool_call_id: string;
        tool_args: Record<string, unknown>;
      };
    }
  | {
      event: "tool_call_result";
      data: { tool_name: string; tool_call_id: string; result: string };
    }
  | { event: "message_complete"; data: { content: string } }
  | { event: "error"; data: { message: string } };
