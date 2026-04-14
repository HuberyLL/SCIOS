"use client";

import { useEffect, useRef, useState } from "react";
import { getLandscapeStatus, landscapeStreamUrl } from "@/lib/api";
import type {
  DynamicResearchLandscape,
  LandscapeSSEEvent,
  LandscapeTaskListItem,
  PipelineStage,
  StageId,
  TaskStatus,
} from "@/types";

// ---------------------------------------------------------------------------
// Stage definitions (matches backend _STAGES)
// ---------------------------------------------------------------------------

const STAGE_DEFINITIONS: { id: StageId; label: string; index: number }[] = [
  { id: "scope", label: "Scope Agent", index: 1 },
  { id: "retrieval", label: "Retrieval Agent", index: 2 },
  { id: "taxonomy", label: "Taxonomy Agent", index: 3 },
  { id: "network", label: "Network Agent", index: 4 },
  { id: "gaps", label: "Gap Agent", index: 4 },
  { id: "critic", label: "Critic Agent", index: 5 },
  { id: "assembler", label: "Assembler", index: 6 },
];

function createInitialStages(): PipelineStage[] {
  return STAGE_DEFINITIONS.map((d) => ({
    id: d.id,
    label: d.label,
    index: d.index,
    status: "pending",
    messages: [],
    elapsed_s: 0,
    detail: null,
  }));
}

// ---------------------------------------------------------------------------
// Public interface
// ---------------------------------------------------------------------------

export interface UseLandscapeTaskStatusReturn {
  status: TaskStatus | null;
  landscape: DynamicResearchLandscape | null;
  messages: string[];
  stages: PipelineStage[];
  progressPct: number;
  error: string | null;
  loading: boolean;
}

interface InternalState {
  taskKey: string | null;
  status: TaskStatus | null;
  landscape: DynamicResearchLandscape | null;
  messages: string[];
  stages: PipelineStage[];
  progressPct: number;
  error: string | null;
  loading: boolean;
}

const POLL_INTERVAL = 2_500;

function applyProgressEvent(
  prev: InternalState,
  data: LandscapeSSEEvent & { type: "progress" },
): InternalState {
  const stageId = data.stage_id;
  const stageStatus = (data.status ?? "running") as PipelineStage["status"];
  const pct = data.progress_pct ?? prev.progressPct;
  const newMessages = [...prev.messages, data.message];

  if (!stageId) {
    return {
      ...prev,
      messages: newMessages,
      progressPct: Math.max(prev.progressPct, pct),
    };
  }

  const newStages = prev.stages.map((s) => {
    if (s.id !== stageId) return s;
    return {
      ...s,
      status: stageStatus,
      elapsed_s: data.elapsed_s ?? s.elapsed_s,
      detail: data.detail ?? s.detail,
      messages: [...s.messages, data.message],
    };
  });

  return {
    ...prev,
    messages: newMessages,
    stages: newStages,
    progressPct: Math.max(prev.progressPct, pct),
  };
}

function initialStateFor(task: LandscapeTaskListItem | null): InternalState {
  if (!task) {
    return {
      taskKey: null, status: null, landscape: null, messages: [],
      stages: createInitialStages(), progressPct: 0,
      error: null, loading: false,
    };
  }
  if (task.status === "completed") {
    return {
      taskKey: task.task_id, status: "completed", landscape: null, messages: [],
      stages: createInitialStages(), progressPct: 100,
      error: null, loading: true,
    };
  }
  if (task.status === "failed") {
    return {
      taskKey: task.task_id, status: "failed", landscape: null, messages: [],
      stages: createInitialStages(), progressPct: 0,
      error: task.progress_message || "Task failed", loading: false,
    };
  }
  return {
    taskKey: task.task_id, status: task.status, landscape: null, messages: [],
    stages: createInitialStages(), progressPct: 0,
    error: null, loading: false,
  };
}

/**
 * Subscribes to a selected landscape task's real-time status with structured
 * stage tracking for the Pipeline Stepper UI.
 */
export function useLandscapeTaskStatus(
  task: LandscapeTaskListItem | null,
  onStatusChange?: () => void,
): UseLandscapeTaskStatusReturn {
  const [state, setState] = useState<InternalState>(() => initialStateFor(task));

  const onStatusChangeRef = useRef(onStatusChange);
  useEffect(() => {
    onStatusChangeRef.current = onStatusChange;
  }, [onStatusChange]);

  const taskId = task?.task_id ?? null;
  const taskStatus = task?.status ?? null;

  useEffect(() => {
    setState((prev) => {
      if (prev.taskKey === taskId) return prev;
      return initialStateFor(task);
    });
  }, [taskId, task]);

  // Completed tasks: fetch result once
  useEffect(() => {
    if (!taskId || taskStatus !== "completed") return;
    let cancelled = false;

    getLandscapeStatus(taskId)
      .then((res) => {
        if (cancelled) return;
        setState((prev) => ({
          ...prev,
          status: "completed",
          landscape: res.result,
          loading: false,
          progressPct: 100,
        }));
      })
      .catch(() => {
        if (cancelled) return;
        setState((prev) => ({
          ...prev,
          status: "failed",
          error: "Failed to load results",
          loading: false,
        }));
      });

    return () => { cancelled = true; };
  }, [taskId, taskStatus]);

  // Pending/running tasks: SSE + polling
  useEffect(() => {
    if (!taskId || (taskStatus !== "pending" && taskStatus !== "running")) return;

    let cancelled = false;
    let timer: ReturnType<typeof setTimeout> | null = null;

    const es = new EventSource(landscapeStreamUrl(taskId));

    es.onmessage = (event) => {
      if (cancelled) return;
      try {
        const data = JSON.parse(event.data) as LandscapeSSEEvent;

        switch (data.type) {
          case "progress": {
            setState((prev) => applyProgressEvent(prev, data));
            break;
          }
          case "status":
            setState((prev) => ({
              ...prev,
              status: data.status as TaskStatus,
            }));
            break;
          case "complete":
            setState((prev) => ({
              ...prev,
              status: "completed",
              landscape: data.result ?? null,
              progressPct: 100,
            }));
            es.close();
            onStatusChangeRef.current?.();
            break;
          case "error":
            setState((prev) => ({
              ...prev,
              status: "failed",
              error: data.message ?? "Task failed",
            }));
            es.close();
            onStatusChangeRef.current?.();
            break;
          case "timeout":
            setState((prev) => ({
              ...prev,
              status: "failed",
              error: data.message,
            }));
            es.close();
            onStatusChangeRef.current?.();
            break;
        }
      } catch {
        // malformed JSON — skip
      }
    };

    es.onerror = () => {
      if (cancelled) return;
      setState((prev) => ({
        ...prev,
        status: "failed",
        error: "Lost connection to server",
      }));
      es.close();
    };

    // Polling fallback
    const poll = async () => {
      if (cancelled) return;
      try {
        const res = await getLandscapeStatus(taskId);
        if (cancelled) return;

        if (res.status === "completed" && res.result) {
          setState((prev) => ({
            ...prev,
            status: "completed",
            landscape: res.result,
            progressPct: 100,
          }));
          es.close();
          onStatusChangeRef.current?.();
          return;
        }
        if (res.status === "running" || res.status === "pending") {
          setState((prev) => {
            let next: InternalState = {
              ...prev,
              status: res.status,
              progressPct: Math.max(
                prev.progressPct,
                res.current_progress_pct ?? prev.progressPct,
              ),
            };

            const snapshot = res.progress_snapshot ?? {};
            const events = Object.values(snapshot).filter(
              (e): e is LandscapeSSEEvent & { type: "progress" } =>
                !!e && typeof e === "object" && e.type === "progress" && typeof e.message === "string",
            );
            events.sort((a, b) => {
              const ai = a.stage_index ?? 999;
              const bi = b.stage_index ?? 999;
              if (ai !== bi) return ai - bi;
              const ap = a.progress_pct ?? 0;
              const bp = b.progress_pct ?? 0;
              return ap - bp;
            });

            const seen = new Set(next.messages);
            for (const ev of events) {
              if (seen.has(ev.message)) continue;
              next = applyProgressEvent(next, ev);
              seen.add(ev.message);
            }
            return next;
          });
        }
        if (res.status === "failed") {
          setState((prev) => ({
            ...prev,
            status: "failed",
            error: res.progress_message || "Task failed",
          }));
          es.close();
          onStatusChangeRef.current?.();
          return;
        }
      } catch {
        // keep polling
      }
      if (!cancelled) timer = setTimeout(poll, POLL_INTERVAL);
    };

    timer = setTimeout(poll, POLL_INTERVAL);

    return () => {
      cancelled = true;
      if (timer) clearTimeout(timer);
      es.close();
    };
  }, [taskId, taskStatus]);

  return {
    status: state.status,
    landscape: state.landscape,
    messages: state.messages,
    stages: state.stages,
    progressPct: state.progressPct,
    error: state.error,
    loading: state.loading,
  };
}
