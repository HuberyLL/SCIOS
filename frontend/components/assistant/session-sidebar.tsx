"use client";

import { useCallback, useEffect, useState } from "react";
import {
  createAssistantSession,
  deleteAssistantSession,
  listAssistantSessions,
} from "@/lib/api";
import type { AssistantSession } from "@/types";
import { Button } from "@/components/ui/button";
import { ScrollArea } from "@/components/ui/scroll-area";
import { Skeleton } from "@/components/ui/skeleton";
import { cn } from "@/lib/utils";
import {
  Plus,
  MessageSquare,
  Trash2,
  AlertCircle,
} from "lucide-react";

interface SessionSidebarProps {
  currentSessionId: string | null;
  onSelectSession: (id: string) => void;
  onNewSession: (id: string) => void;
}

export function SessionSidebar({
  currentSessionId,
  onSelectSession,
  onNewSession,
}: SessionSidebarProps) {
  const [sessions, setSessions] = useState<AssistantSession[]>([]);
  const [loading, setLoading] = useState(true);
  const [creating, setCreating] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const fetchSessions = useCallback(async () => {
    try {
      setError(null);
      const list = await listAssistantSessions();
      setSessions(list);
    } catch {
      setError("Failed to load sessions");
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    fetchSessions();
  }, [fetchSessions]);

  const handleCreate = async () => {
    try {
      setCreating(true);
      const session = await createAssistantSession();
      setSessions((prev) => [session, ...prev]);
      onNewSession(session.id);
    } catch {
      setError("Failed to create session");
    } finally {
      setCreating(false);
    }
  };

  const handleDelete = async (e: React.MouseEvent, id: string) => {
    e.stopPropagation();
    try {
      await deleteAssistantSession(id);
      setSessions((prev) => prev.filter((s) => s.id !== id));
      if (currentSessionId === id) {
        onSelectSession("");
      }
    } catch {
      /* ignore */
    }
  };

  const formatDate = (iso: string) => {
    const d = new Date(iso);
    if (Number.isNaN(d.getTime())) return "";
    const now = new Date();
    const diff = Math.max(0, now.getTime() - d.getTime());
    if (diff < 60_000) return "just now";
    if (diff < 3_600_000) return `${Math.floor(diff / 60_000)}m ago`;
    if (diff < 86_400_000) return `${Math.floor(diff / 3_600_000)}h ago`;
    return d.toLocaleDateString();
  };

  return (
    <aside className="flex w-60 shrink-0 flex-col border-r border-border/40 bg-muted/30">
      <div className="flex items-center justify-between p-3">
        <span className="text-xs font-medium text-muted-foreground uppercase tracking-wider">
          Sessions
        </span>
        <Button
          variant="ghost"
          size="icon"
          className="h-7 w-7"
          onClick={handleCreate}
          disabled={creating}
        >
          <Plus className="h-4 w-4" />
        </Button>
      </div>

      <ScrollArea className="flex-1">
        <div className="space-y-0.5 px-2 pb-2">
          {loading && (
            <>
              {Array.from({ length: 4 }).map((_, i) => (
                <Skeleton key={i} className="h-12 w-full rounded-md" />
              ))}
            </>
          )}

          {error && (
            <div className="flex items-center gap-2 px-2 py-3 text-xs text-destructive">
              <AlertCircle className="h-3.5 w-3.5 shrink-0" />
              {error}
            </div>
          )}

          {!loading &&
            !error &&
            sessions.map((s) => (
              <div
                key={s.id}
                role="button"
                tabIndex={0}
                onClick={() => onSelectSession(s.id)}
                onKeyDown={(e) => {
                  if (e.key === "Enter" || e.key === " ") {
                    e.preventDefault();
                    onSelectSession(s.id);
                  }
                }}
                className={cn(
                  "group relative flex w-full cursor-pointer items-start gap-2 rounded-md px-2.5 py-2 pr-8 text-left transition-colors",
                  currentSessionId === s.id
                    ? "bg-accent text-accent-foreground"
                    : "text-muted-foreground hover:bg-accent/50 hover:text-foreground",
                )}
              >
                <MessageSquare className="mt-0.5 h-3.5 w-3.5 shrink-0" />
                <div className="flex-1 min-w-0">
                  <div className="truncate text-xs font-medium">
                    {s.title}
                  </div>
                  <div className="text-[10px] text-muted-foreground/70">
                    {formatDate(s.updated_at)}
                  </div>
                </div>
                <button
                  onClick={(e) => handleDelete(e, s.id)}
                  title="Delete session"
                  aria-label="Delete session"
                  className={cn(
                    "absolute right-2 top-2 flex h-5 w-5 shrink-0 items-center justify-center rounded text-muted-foreground/60 hover:bg-destructive/10 hover:text-destructive",
                    currentSessionId === s.id
                      ? "opacity-100"
                      : "pointer-events-none opacity-0 group-hover:pointer-events-auto group-hover:opacity-100",
                  )}
                >
                  <Trash2 className="h-3 w-3" />
                </button>
              </div>
            ))}

          {!loading && !error && sessions.length === 0 && (
            <p className="px-2 py-6 text-center text-xs text-muted-foreground/60">
              No sessions yet.
            </p>
          )}
        </div>
      </ScrollArea>
    </aside>
  );
}
