"use client";

import { useEffect, useRef, useState } from "react";
import { explorationStreamUrl } from "@/lib/api";
import type { ExplorationReport, SSEEvent, TaskStatus } from "@/types";

export interface StreamState {
  messages: string[];
  status: TaskStatus | null;
  report: ExplorationReport | null;
  error: string | null;
}

const INITIAL_STATE: StreamState = {
  messages: [],
  status: null,
  report: null,
  error: null,
};

export function useExplorationStream(taskId: string | null): StreamState {
  const [state, setState] = useState<StreamState>(() =>
    taskId ? { ...INITIAL_STATE, status: "running" } : INITIAL_STATE,
  );
  const esRef = useRef<EventSource | null>(null);

  useEffect(() => {
    if (!taskId) {
      return;
    }

    const es = new EventSource(explorationStreamUrl(taskId));
    esRef.current = es;

    es.onmessage = (event) => {
      try {
        const data = JSON.parse(event.data) as SSEEvent;

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
              report: data.result ?? null,
            }));
            es.close();
            break;

          case "error":
            setState((prev) => ({
              ...prev,
              status: "failed",
              error: data.message ?? "Exploration failed",
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
