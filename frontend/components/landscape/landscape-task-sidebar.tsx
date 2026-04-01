"use client";

import { useState } from "react";
import { motion, AnimatePresence } from "framer-motion";
import {
  Clock,
  Loader2,
  Plus,
  Search,
  Trash2,
  CheckCircle2,
  XCircle,
  Circle,
} from "lucide-react";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { ScrollArea } from "@/components/ui/scroll-area";
import { Separator } from "@/components/ui/separator";
import { cn } from "@/lib/utils";
import type { LandscapeTaskListItem, TaskStatus } from "@/types";

interface LandscapeTaskSidebarProps {
  tasks: LandscapeTaskListItem[];
  selectedId: string | null;
  loading: boolean;
  onSelect: (taskId: string) => void;
  onCreate: (topic: string) => Promise<void>;
  onDelete: (taskId: string) => void;
}

const STATUS_CONFIG: Record<
  TaskStatus,
  { label: string; variant: "default" | "secondary" | "destructive" | "outline"; icon: React.ElementType }
> = {
  pending: { label: "Pending", variant: "outline", icon: Circle },
  running: { label: "Running", variant: "secondary", icon: Loader2 },
  completed: { label: "Done", variant: "default", icon: CheckCircle2 },
  failed: { label: "Failed", variant: "destructive", icon: XCircle },
};

function formatDate(iso: string): string {
  const normalized = /([zZ]|[+-]\d{2}:\d{2})$/.test(iso) ? iso : `${iso}Z`;
  const date = new Date(normalized);
  return date.toLocaleString(undefined, {
    month: "2-digit",
    day: "2-digit",
    hour: "2-digit",
    minute: "2-digit",
    hour12: false,
    timeZone: Intl.DateTimeFormat().resolvedOptions().timeZone,
  });
}

export function LandscapeTaskSidebar({
  tasks,
  selectedId,
  loading,
  onSelect,
  onCreate,
  onDelete,
}: LandscapeTaskSidebarProps) {
  const [topic, setTopic] = useState("");
  const [creating, setCreating] = useState(false);

  const handleCreate = async () => {
    const trimmed = topic.trim();
    if (!trimmed || creating) return;
    setCreating(true);
    try {
      await onCreate(trimmed);
      setTopic("");
    } finally {
      setCreating(false);
    }
  };

  return (
    <div className="flex h-full flex-col border-r border-border/40 bg-muted/20">
      {/* Create task form */}
      <div className="space-y-3 p-4">
        <h2 className="text-sm font-semibold tracking-tight">Landscape Tasks</h2>
        <div className="flex gap-2">
          <div className="relative flex-1">
            <Search className="absolute left-2.5 top-1/2 h-3.5 w-3.5 -translate-y-1/2 text-muted-foreground" />
            <Input
              value={topic}
              onChange={(e) => setTopic(e.target.value)}
              onKeyDown={(e) => e.key === "Enter" && handleCreate()}
              placeholder="Research topic..."
              className="h-8 pl-8 text-xs"
              disabled={creating}
            />
          </div>
          <Button
            size="sm"
            className="h-8 w-8 shrink-0 p-0"
            onClick={handleCreate}
            disabled={!topic.trim() || creating}
          >
            {creating ? (
              <Loader2 className="h-3.5 w-3.5 animate-spin" />
            ) : (
              <Plus className="h-3.5 w-3.5" />
            )}
          </Button>
        </div>
      </div>

      <Separator className="opacity-50" />

      {/* Task list */}
      {loading ? (
        <div className="flex flex-1 items-center justify-center">
          <Loader2 className="h-4 w-4 animate-spin text-muted-foreground" />
        </div>
      ) : tasks.length === 0 ? (
        <div className="flex flex-1 items-center justify-center p-4">
          <p className="text-center text-xs text-muted-foreground">
            No tasks yet. Enter a topic above to start exploring.
          </p>
        </div>
      ) : (
        <ScrollArea className="flex-1">
          <div className="space-y-0.5 p-2">
            <AnimatePresence initial={false}>
              {tasks.map((task, i) => {
                const cfg = STATUS_CONFIG[task.status];
                const Icon = cfg.icon;
                return (
                  <motion.div
                    key={task.task_id}
                    initial={{ opacity: 0, x: -8 }}
                    animate={{ opacity: 1, x: 0 }}
                    exit={{ opacity: 0, x: -8 }}
                    transition={{ delay: i * 0.02 }}
                    onClick={() => onSelect(task.task_id)}
                    onKeyDown={(e) => {
                      if (e.key === "Enter" || e.key === " ") {
                        e.preventDefault();
                        onSelect(task.task_id);
                      }
                    }}
                    role="button"
                    tabIndex={0}
                    className={cn(
                      "group flex w-full flex-col gap-1.5 rounded-md px-3 py-2.5 text-left transition-colors cursor-pointer",
                      selectedId === task.task_id
                        ? "bg-accent"
                        : "hover:bg-muted/60",
                    )}
                  >
                    <div className="flex items-start justify-between gap-2">
                      <span className="line-clamp-2 text-xs font-medium leading-relaxed">
                        {task.topic}
                      </span>
                      <button
                        type="button"
                        onClick={(e) => {
                          e.stopPropagation();
                          onDelete(task.task_id);
                        }}
                        className="mt-0.5 shrink-0 rounded p-0.5 text-muted-foreground/40 transition-colors hover:bg-destructive/10 hover:text-destructive"
                        aria-label={`Delete ${task.topic}`}
                      >
                        <Trash2 className="h-3.5 w-3.5" />
                      </button>
                    </div>
                    <div className="flex items-center justify-between">
                      <div className="flex items-center gap-1 text-[10px] text-muted-foreground">
                        <Clock className="h-2.5 w-2.5" />
                        {formatDate(task.updated_at)}
                      </div>
                      <Badge
                        variant={cfg.variant}
                        className="gap-1 px-1.5 py-0 text-[9px]"
                      >
                        <Icon
                          className={cn(
                            "h-2.5 w-2.5",
                            task.status === "running" && "animate-spin",
                          )}
                        />
                        {cfg.label}
                      </Badge>
                    </div>
                  </motion.div>
                );
              })}
            </AnimatePresence>
          </div>
        </ScrollArea>
      )}
    </div>
  );
}
