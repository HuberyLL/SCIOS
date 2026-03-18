"use client";

import { motion } from "framer-motion";
import { Radio, Clock } from "lucide-react";
import { Badge } from "@/components/ui/badge";
import { ScrollArea } from "@/components/ui/scroll-area";
import { cn } from "@/lib/utils";
import type { MonitorTaskData } from "@/types";

interface TaskListProps {
  tasks: MonitorTaskData[];
  selectedId: string | null;
  onSelect: (taskId: string) => void;
}

function formatDate(iso: string | null): string {
  if (!iso) return "Never";
  return new Date(iso).toLocaleDateString("en-US", {
    month: "short",
    day: "numeric",
    hour: "2-digit",
    minute: "2-digit",
  });
}

export function TaskList({ tasks, selectedId, onSelect }: TaskListProps) {
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
          <motion.button
            key={task.id}
            initial={{ opacity: 0, x: -8 }}
            animate={{ opacity: 1, x: 0 }}
            transition={{ delay: i * 0.04 }}
            onClick={() => onSelect(task.id)}
            className={cn(
              "flex w-full flex-col gap-1 rounded-lg px-3 py-2.5 text-left transition-colors",
              selectedId === task.id
                ? "bg-accent"
                : "hover:bg-muted/50",
            )}
          >
            <div className="flex items-center justify-between gap-2">
              <span className="truncate text-sm font-medium">{task.topic}</span>
              <Badge
                variant={task.is_active ? "secondary" : "outline"}
                className="shrink-0 text-[10px]"
              >
                {task.frequency}
              </Badge>
            </div>
            <div className="flex items-center gap-1.5 text-[11px] text-muted-foreground">
              <Clock className="h-3 w-3" />
              Last run: {formatDate(task.last_run_at)}
            </div>
          </motion.button>
        ))}
      </div>
    </ScrollArea>
  );
}
