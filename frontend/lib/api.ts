import type {
  ApiResponse,
  BriefData,
  CreateMonitorRequest,
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
  return request<MonitorTaskData[]>("/monitoring/tasks");
}

export async function listBriefs(taskId: string): Promise<BriefData[]> {
  return request<BriefData[]>(`/monitoring/tasks/${taskId}/briefs`);
}
