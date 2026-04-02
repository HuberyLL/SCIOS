"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import {
  deleteLandscapeTask,
  listLandscapeTasks,
  startLandscape,
} from "@/lib/api";
import type { LandscapeTaskListItem } from "@/types";

const POLL_INTERVAL = 10_000;

export interface UseLandscapeTasksReturn {
  tasks: LandscapeTaskListItem[];
  loading: boolean;
  selectedId: string | null;
  setSelectedId: (id: string | null) => void;
  createTask: (topic: string) => Promise<void>;
  deleteTask: (taskId: string) => Promise<void>;
  refresh: () => Promise<void>;
}

export function useLandscapeTasks(): UseLandscapeTasksReturn {
  const [tasks, setTasks] = useState<LandscapeTaskListItem[]>([]);
  const [loading, setLoading] = useState(true);
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const initialLoadDone = useRef(false);

  const refresh = useCallback(async () => {
    try {
      const data = await listLandscapeTasks();
      setTasks(data);
    } catch {
      // silent — keep current list
    } finally {
      if (!initialLoadDone.current) {
        initialLoadDone.current = true;
        setLoading(false);
      }
    }
  }, []);

  useEffect(() => {
    refresh();
  }, [refresh]);

  // Poll for status updates on in-flight tasks
  useEffect(() => {
    const hasActiveTask = tasks.some(
      (t) => t.status === "pending" || t.status === "running",
    );
    if (!hasActiveTask) return;

    const timer = setInterval(refresh, POLL_INTERVAL);
    return () => clearInterval(timer);
  }, [tasks, refresh]);

  const createTask = useCallback(
    async (topic: string) => {
      const { task_id } = await startLandscape(topic);
      const newItem: LandscapeTaskListItem = {
        task_id,
        topic,
        status: "pending",
        progress_message: "",
        has_result: false,
        created_at: new Date().toISOString(),
        updated_at: new Date().toISOString(),
      };
      setTasks((prev) => [newItem, ...prev]);
      setSelectedId(task_id);
    },
    [],
  );

  const deleteTask = useCallback(
    async (taskId: string) => {
      try {
        await deleteLandscapeTask(taskId);
        setTasks((prev) => prev.filter((t) => t.task_id !== taskId));
        if (selectedId === taskId) setSelectedId(null);
      } catch {
        // keep list unchanged on failure
      }
    },
    [selectedId],
  );

  return {
    tasks,
    loading,
    selectedId,
    setSelectedId,
    createTask,
    deleteTask,
    refresh,
  };
}
