"use client";

import { useEffect, useRef, useState } from "react";
import { landscapeStreamUrl } from "@/lib/api";
import type {
  DynamicResearchLandscape,
  LandscapeSSEEvent,
  TaskStatus,
} from "@/types";

export interface LandscapeStreamState {
  messages: string[];
  status: TaskStatus | null;
  landscape: DynamicResearchLandscape | null;
  error: string | null;
}

const INITIAL_STATE: LandscapeStreamState = {
  messages: [],
  status: null,
  landscape: null,
  error: null,
};

export function useLandscapeStream(
  taskId: string | null,
): LandscapeStreamState {
  const [state, setState] = useState<LandscapeStreamState>(() =>
    taskId ? { ...INITIAL_STATE, status: "running" } : INITIAL_STATE,
  );
  const esRef = useRef<EventSource | null>(null);

  useEffect(() => {
    if (!taskId) return;

    const es = new EventSource(landscapeStreamUrl(taskId));
    esRef.current = es;

    es.onmessage = (event) => {
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
            break;

          case "error":
            setState((prev) => ({
              ...prev,
              status: "failed",
              error: data.message ?? "Landscape analysis failed",
            }));
            es.close();
            break;

          case "timeout":
            setState((prev) => ({
              ...prev,
              status: "failed",
              error: data.message,
            }));
            es.close();
            break;
        }
      } catch {
        // malformed JSON — ignore
      }
    };

    es.onerror = () => {
      setState((prev) => ({
        ...prev,
        status: "failed",
        error: "Lost connection to server",
      }));
      es.close();
    };

    return () => {
      es.close();
      esRef.current = null;
    };
  }, [taskId]);

  return state;
}
