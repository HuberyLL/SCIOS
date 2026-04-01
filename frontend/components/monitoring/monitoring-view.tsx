"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import { motion } from "framer-motion";
import { Loader2 } from "lucide-react";
import { Separator } from "@/components/ui/separator";
import { SubscribeForm } from "./subscribe-form";
import { TaskList } from "./task-list";
import { BriefDetail } from "./brief-detail";
import { deleteMonitorTask, listMonitorTasks, monitoringStreamUrl } from "@/lib/api";
import type { MonitorTaskData, MonitoringSSEEvent } from "@/types";

export function MonitoringView() {
  const [tasks, setTasks] = useState<MonitorTaskData[]>([]);
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);
  const [refreshSignal, setRefreshSignal] = useState(0);
  const selectedIdRef = useRef<string | null>(null);

  const fetchTasks = useCallback(async () => {
    try {
      const data = await listMonitorTasks();
      setTasks(data);
    } catch {
      // silent fail — list stays empty
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    fetchTasks();
  }, [fetchTasks]);

  useEffect(() => {
    selectedIdRef.current = selectedId;
  }, [selectedId]);

  useEffect(() => {
    const es = new EventSource(monitoringStreamUrl());

    es.onmessage = (ev) => {
      try {
        const event = JSON.parse(ev.data) as MonitoringSSEEvent;
        if (
          event.type === "task_started" ||
          event.type === "task_completed" ||
          event.type === "task_failed"
        ) {
          fetchTasks();
          if (selectedIdRef.current && event.task_id === selectedIdRef.current) {
            setRefreshSignal((n) => n + 1);
          }
        }
      } catch {
        // Ignore malformed SSE payloads.
      }
    };

    es.onerror = () => {
      // Browser auto-reconnects EventSource; no manual retry needed here.
    };

    return () => {
      es.close();
    };
  }, [fetchTasks]);

  useEffect(() => {
    const timer = setInterval(() => {
      fetchTasks();
    }, 12000);

    return () => {
      clearInterval(timer);
    };
  }, [fetchTasks]);

  const handleCreated = () => {
    fetchTasks();
  };

  const handleDelete = async (taskId: string) => {
    try {
      await deleteMonitorTask(taskId);
      setTasks((prev) => prev.filter((t) => t.id !== taskId));
      if (selectedId === taskId) {
        setSelectedId(null);
      }
    } catch {
      // keep current list unchanged on delete failure
    }
  };

  const selectedTask = tasks.find((t) => t.id === selectedId);

  return (
    <motion.div
      initial={{ opacity: 0, y: 10 }}
      animate={{ opacity: 1, y: 0 }}
      className="mx-auto max-w-6xl px-6 py-8"
    >
      <div className="mb-8">
        <h1 className="text-2xl font-bold tracking-tight">Topic Monitoring</h1>
        <p className="mt-1 text-sm text-muted-foreground">
          Subscribe to research topics and receive periodic briefs on new
          developments.
        </p>
      </div>

      <div className="grid gap-6 lg:grid-cols-[280px_1fr]">
        {/* Left column: subscribe form + task list */}
        <div className="space-y-6">
          <SubscribeForm onCreated={handleCreated} />

          <Separator />

          {loading ? (
            <div className="flex h-20 items-center justify-center">
              <Loader2 className="h-4 w-4 animate-spin text-muted-foreground" />
            </div>
          ) : (
            <TaskList
              tasks={tasks}
              selectedId={selectedId}
              onSelect={setSelectedId}
              onDelete={handleDelete}
            />
          )}
        </div>

        {/* Right column: brief detail */}
        <div className="min-h-[50vh] rounded-lg border border-border/30 bg-muted/10 p-6">
          <BriefDetail
            taskId={selectedId}
            taskTopic={selectedTask?.topic}
            refreshSignal={refreshSignal}
          />
        </div>
      </div>
    </motion.div>
  );
}
