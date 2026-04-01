"use client";

import { motion } from "framer-motion";
import { Clock, Trash2 } from "lucide-react";
import { Badge } from "@/components/ui/badge";
import { ScrollArea } from "@/components/ui/scroll-area";
import { cn } from "@/lib/utils";
import type { MonitorTaskData } from "@/types";

interface TaskListProps {
  tasks: MonitorTaskData[];
  selectedId: string | null;
  onSelect: (taskId: string) => void;
  onDelete: (taskId: string) => void;
}

function formatDate(iso: string | null): string {
  if (!iso) return "Never";
  // If backend timestamp has no explicit offset, treat it as UTC.
  const normalized = /([zZ]|[+-]\d{2}:\d{2})$/.test(iso) ? iso : `${iso}Z`;
  const date = new Date(normalized);
  return date.toLocaleString(undefined, {
    year: "numeric",
    month: "2-digit",
    day: "2-digit",
    hour: "2-digit",
    minute: "2-digit",
    hour12: false,
    timeZone: Intl.DateTimeFormat().resolvedOptions().timeZone,
  });
}

export function TaskList({ tasks, selectedId, onSelect, onDelete }: TaskListProps) {
  if (tasks.length === 0) {
    return (
      <div className="flex h-40 items-center justify-center">
        <p className="text-xs text-muted-foreground">No subscriptions yet.</p>
      </div>
    );
  }

  return (
    <ScrollArea className="h-[calc(100vh-18rem)]">
      <div className="space-y-1 pr-2">
        {tasks.map((task, i) => (
          <motion.div
            key={task.id}
            initial={{ opacity: 0, x: -8 }}
            animate={{ opacity: 1, x: 0 }}
            transition={{ delay: i * 0.04 }}
            onClick={() => onSelect(task.id)}
            onKeyDown={(e) => {
              if (e.key === "Enter" || e.key === " ") {
                e.preventDefault();
                onSelect(task.id);
              }
            }}
            role="button"
            tabIndex={0}
            className={cn(
              "flex w-full flex-col gap-1 rounded-lg px-3 py-2.5 text-left transition-colors",
              selectedId === task.id
                ? "bg-accent"
                : "hover:bg-muted/50",
            )}
          >
            <div className="flex items-center justify-between gap-2">
              <span className="truncate pr-1 text-sm font-medium">{task.topic}</span>
              <div className="flex items-center gap-1">
                <Badge
                  variant={task.is_active ? "secondary" : "outline"}
                  className="shrink-0 text-[10px]"
                >
                  {task.frequency}
                </Badge>
                <button
                  type="button"
                  onClick={(e) => {
                    e.stopPropagation();
                    onDelete(task.id);
                  }}
                  className="rounded p-1 text-muted-foreground hover:bg-muted hover:text-foreground"
                  aria-label={`Delete ${task.topic}`}
                  title="Remove task"
                >
                  <Trash2 className="h-3.5 w-3.5" />
                </button>
              </div>
            </div>
            <div className="flex items-center gap-1.5 text-[11px] text-muted-foreground">
              <Clock className="h-3 w-3" />
              Last run: {formatDate(task.last_run_at)}
            </div>
          </motion.div>
        ))}
      </div>
    </ScrollArea>
  );
}
