"use client";

import { useCallback, useMemo } from "react";
import { motion } from "framer-motion";
import { Map, RotateCcw, AlertCircle } from "lucide-react";
import { Button } from "@/components/ui/button";
import { LandscapeTaskSidebar } from "./landscape-task-sidebar";
import { LandscapeProgress } from "./landscape-progress";
import { LandscapeBoard } from "./landscape-board";
import { useLandscapeTasks } from "@/hooks/use-landscape-tasks";
import { useLandscapeTaskStatus } from "@/hooks/use-landscape-task-status";

export function LandscapeWorkspace() {
  const {
    tasks,
    loading,
    selectedId,
    setSelectedId,
    createTask,
    deleteTask,
    refresh,
  } = useLandscapeTasks();

  const selectedTask = useMemo(
    () => tasks.find((t) => t.task_id === selectedId) ?? null,
    [tasks, selectedId],
  );

  const onStatusChange = useCallback(() => {
    refresh();
  }, [refresh]);

  const { status, landscape, messages, error, loading: resultLoading } =
    useLandscapeTaskStatus(selectedTask, onStatusChange);

  const handleRetry = useCallback(() => {
    if (selectedTask) {
      createTask(selectedTask.topic);
    }
  }, [selectedTask, createTask]);

  return (
    <div className="grid h-[calc(100vh-3.5rem)] lg:grid-cols-[300px_1fr]">
      {/* Left sidebar */}
      <LandscapeTaskSidebar
        tasks={tasks}
        selectedId={selectedId}
        loading={loading}
        onSelect={setSelectedId}
        onCreate={createTask}
        onDelete={deleteTask}
      />

      {/* Right content area */}
      <div className="flex flex-col overflow-hidden">
        {!selectedId ? (
          <EmptyState />
        ) : status === "pending" || status === "running" ? (
          <LandscapeProgress
            messages={messages}
            status={status}
            error={error}
          />
        ) : status === "completed" && landscape ? (
          <LandscapeBoard landscape={landscape} />
        ) : status === "failed" ? (
          <FailedState
            error={error}
            onRetry={handleRetry}
          />
        ) : resultLoading ? (
          <div className="flex flex-1 items-center justify-center">
            <div className="h-5 w-5 animate-spin rounded-full border-2 border-muted-foreground border-t-transparent" />
          </div>
        ) : (
          <EmptyState />
        )}
      </div>
    </div>
  );
}

function EmptyState() {
  return (
    <div className="flex flex-1 items-center justify-center p-8">
      <motion.div
        initial={{ opacity: 0, y: 10 }}
        animate={{ opacity: 1, y: 0 }}
        className="text-center"
      >
        <div className="mx-auto mb-4 flex h-12 w-12 items-center justify-center rounded-full bg-muted">
          <Map className="h-5 w-5 text-muted-foreground" />
        </div>
        <h3 className="mb-1 text-sm font-medium">No task selected</h3>
        <p className="max-w-xs text-xs text-muted-foreground">
          Create a new landscape task or select an existing one from the sidebar
          to view results.
        </p>
      </motion.div>
    </div>
  );
}

function FailedState({
  error,
  onRetry,
}: {
  error: string | null;
  onRetry: () => void;
}) {
  return (
    <div className="flex flex-1 items-center justify-center p-8">
      <motion.div
        initial={{ opacity: 0, y: 10 }}
        animate={{ opacity: 1, y: 0 }}
        className="text-center"
      >
        <div className="mx-auto mb-4 flex h-12 w-12 items-center justify-center rounded-full bg-destructive/10">
          <AlertCircle className="h-5 w-5 text-destructive" />
        </div>
        <h3 className="mb-1 text-sm font-medium">Analysis Failed</h3>
        <p className="mb-4 max-w-xs text-xs text-muted-foreground">
          {error ?? "Something went wrong during the landscape analysis."}
        </p>
        <Button variant="outline" size="sm" onClick={onRetry} className="gap-2">
          <RotateCcw className="h-3.5 w-3.5" />
          Retry with same topic
        </Button>
      </motion.div>
    </div>
  );
}
