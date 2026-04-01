"use client";

import { useEffect, useRef, useState } from "react";
import { getLandscapeStatus, landscapeStreamUrl } from "@/lib/api";
import type {
  DynamicResearchLandscape,
  LandscapeSSEEvent,
  LandscapeTaskListItem,
  TaskStatus,
} from "@/types";

export interface UseLandscapeTaskStatusReturn {
  status: TaskStatus | null;
  landscape: DynamicResearchLandscape | null;
  messages: string[];
  error: string | null;
  loading: boolean;
}

interface InternalState {
  taskKey: string | null;
  status: TaskStatus | null;
  landscape: DynamicResearchLandscape | null;
  messages: string[];
  error: string | null;
  loading: boolean;
}

const POLL_INTERVAL = 2_500;

function initialStateFor(task: LandscapeTaskListItem | null): InternalState {
  if (!task) {
    return { taskKey: null, status: null, landscape: null, messages: [], error: null, loading: false };
  }
  if (task.status === "completed") {
    return { taskKey: task.task_id, status: "completed", landscape: null, messages: [], error: null, loading: true };
  }
  if (task.status === "failed") {
    return { taskKey: task.task_id, status: "failed", landscape: null, messages: [], error: task.progress_message || "Task failed", loading: false };
  }
  return { taskKey: task.task_id, status: task.status, landscape: null, messages: [], error: null, loading: false };
}

/**
 * Subscribes to a selected landscape task's real-time status.
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

  // Reset state during render when the selected task changes
  if (state.taskKey !== taskId) {
    setState(initialStateFor(task));
  }

  // Completed tasks: fetch result once
  useEffect(() => {
    if (!taskId || taskStatus !== "completed") return;
    let cancelled = false;

    getLandscapeStatus(taskId)
      .then((res) => {
        if (cancelled) return;
        setState((prev) => ({
          ...prev,
          landscape: res.result,
          loading: false,
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
          case "progress":
            setState((prev) => ({
              ...prev,
              messages: [...prev.messages, data.message],
            }));
            break;
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
        // malformed JSON
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
          }));
          es.close();
          onStatusChangeRef.current?.();
          return;
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
    error: state.error,
    loading: state.loading,
  };
}
