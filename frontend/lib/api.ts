import type {
  ApiResponse,
  AssistantMessageOut,
  AssistantSession,
  BriefData,
  CreateMonitorRequest,
  DeleteMonitorTaskData,
  LandscapeTaskStatus,
  MonitorTaskData,
  TaskStatusData,
} from "@/types";

class ApiError extends Error {
  constructor(
    message: string,
    public status: number,
  ) {
    super(message);
    this.name = "ApiError";
  }
}

async function request<T>(
  path: string,
  init?: RequestInit,
): Promise<T> {
  const res = await fetch(`/api/v1${path}`, {
    headers: { "Content-Type": "application/json" },
    ...init,
  });

  if (!res.ok) {
    const body = await res.text().catch(() => "");
    throw new ApiError(body || `HTTP ${res.status}`, res.status);
  }

  const json = (await res.json()) as ApiResponse<T>;
  if (json.error) throw new ApiError(json.error, res.status);
  return json.data;
}

// ---------------------------------------------------------------------------
// Exploration
// ---------------------------------------------------------------------------

export async function startExploration(
  topic: string,
): Promise<{ task_id: string }> {
  return request<{ task_id: string }>("/exploration/start", {
    method: "POST",
    body: JSON.stringify({ topic }),
  });
}

export async function getExplorationStatus(
  taskId: string,
): Promise<TaskStatusData> {
  return request<TaskStatusData>(`/exploration/${taskId}/status`);
}

export function explorationStreamUrl(taskId: string): string {
  return `/api/v1/exploration/${taskId}/stream`;
}

// ---------------------------------------------------------------------------
// Landscape
// ---------------------------------------------------------------------------

export async function startLandscape(
  topic: string,
): Promise<{ task_id: string }> {
  return request<{ task_id: string }>("/landscape/start", {
    method: "POST",
    body: JSON.stringify({ topic }),
  });
}

export async function getLandscapeStatus(
  taskId: string,
): Promise<LandscapeTaskStatus> {
  return request<LandscapeTaskStatus>(`/landscape/${taskId}/status`);
}

export function landscapeStreamUrl(taskId: string): string {
  return `/api/v1/landscape/${taskId}/stream`;
}

// ---------------------------------------------------------------------------
// Monitoring
// ---------------------------------------------------------------------------

export async function createMonitorTask(
  req: CreateMonitorRequest,
): Promise<MonitorTaskData> {
  return request<MonitorTaskData>("/monitoring/tasks", {
    method: "POST",
    body: JSON.stringify(req),
  });
}

export async function listMonitorTasks(): Promise<MonitorTaskData[]> {
  return request<MonitorTaskData[]>("/monitoring/tasks", {
    cache: "no-store",
  });
}

export async function listBriefs(taskId: string): Promise<BriefData[]> {
  return request<BriefData[]>(`/monitoring/tasks/${taskId}/briefs`, {
    cache: "no-store",
  });
}

export async function deleteMonitorTask(taskId: string): Promise<DeleteMonitorTaskData> {
  return request<DeleteMonitorTaskData>(`/monitoring/tasks/${taskId}`, {
    method: "DELETE",
  });
}

export function monitoringStreamUrl(): string {
  return "/api/v1/monitoring/stream";
}

// ---------------------------------------------------------------------------
// Assistant
// ---------------------------------------------------------------------------

export async function createAssistantSession(
  title = "New Chat",
): Promise<AssistantSession> {
  const res = await fetch("/api/v1/assistant/sessions", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ title }),
  });
  if (!res.ok) throw new ApiError(`HTTP ${res.status}`, res.status);
  return res.json() as Promise<AssistantSession>;
}

export async function listAssistantSessions(): Promise<AssistantSession[]> {
  const res = await fetch("/api/v1/assistant/sessions", { cache: "no-store" });
  if (!res.ok) throw new ApiError(`HTTP ${res.status}`, res.status);
  const json = (await res.json()) as { sessions: AssistantSession[] };
  return json.sessions;
}

export async function getAssistantSession(
  sessionId: string,
): Promise<{ session: AssistantSession; messages: AssistantMessageOut[] }> {
  const res = await fetch(`/api/v1/assistant/sessions/${sessionId}`, {
    cache: "no-store",
  });
  if (!res.ok) throw new ApiError(`HTTP ${res.status}`, res.status);
  return res.json() as Promise<{
    session: AssistantSession;
    messages: AssistantMessageOut[];
  }>;
}

export async function deleteAssistantSession(
  sessionId: string,
): Promise<void> {
  const res = await fetch(`/api/v1/assistant/sessions/${sessionId}`, {
    method: "DELETE",
  });
  if (!res.ok && res.status !== 204)
    throw new ApiError(`HTTP ${res.status}`, res.status);
}

export function assistantWsUrl(sessionId: string): string {
  const base =
    process.env.NEXT_PUBLIC_WS_BASE_URL || "ws://localhost:8000";
  return `${base}/api/v1/assistant/ws/${sessionId}`;
}
