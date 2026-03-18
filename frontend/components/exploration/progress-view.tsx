"use client";

import { useEffect, useRef } from "react";
import { motion, AnimatePresence } from "framer-motion";
import { Loader2, AlertCircle, RotateCcw } from "lucide-react";
import { Progress } from "@/components/ui/progress";
import { Skeleton } from "@/components/ui/skeleton";
import { Button } from "@/components/ui/button";
import { useExplorationStream } from "@/hooks/use-exploration-stream";

interface ProgressViewProps {
  taskId: string;
  onComplete: () => void;
  onRetry: () => void;
}

const STAGE_WEIGHTS: Record<string, number> = {
  plan: 15,
  search: 25,
  retriev: 50,
  fetch: 50,
  synthe: 80,
  generat: 85,
  complet: 100,
};

function estimateProgress(messages: string[]): number {
  if (messages.length === 0) return 5;
  const last = messages[messages.length - 1].toLowerCase();
  for (const [keyword, pct] of Object.entries(STAGE_WEIGHTS)) {
    if (last.includes(keyword)) return pct;
  }
  return Math.min(10 + messages.length * 8, 95);
}

export function ProgressView({ taskId, onComplete, onRetry }: ProgressViewProps) {
  const { messages, status, error } = useExplorationStream(taskId);
  const scrollRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    if (status === "completed") onComplete();
  }, [status, onComplete]);

  useEffect(() => {
    scrollRef.current?.scrollTo({
      top: scrollRef.current.scrollHeight,
      behavior: "smooth",
    });
  }, [messages]);

  const progress = estimateProgress(messages);
  const failed = status === "failed";

  return (
    <motion.div
      initial={{ opacity: 0, y: 20 }}
      animate={{ opacity: 1, y: 0 }}
      className="mx-auto flex min-h-[calc(100vh-3.5rem)] max-w-2xl flex-col items-center justify-center gap-8 px-6"
    >
      <div className="w-full text-center">
        <h2 className="mb-2 text-lg font-semibold text-foreground">
          {failed ? "Exploration Failed" : "Exploring..."}
        </h2>
        <p className="text-sm text-muted-foreground">
          {failed
            ? error ?? "Something went wrong."
            : "Retrieving papers, profiling scholars, and synthesizing your report."}
        </p>
      </div>

      {!failed && (
        <div className="w-full space-y-1">
          <Progress value={progress} className="h-1.5" />
          <p className="text-right font-mono text-[11px] text-muted-foreground/60">
            {progress}%
          </p>
        </div>
      )}

      <div
        ref={scrollRef}
        className="w-full max-h-64 overflow-y-auto rounded-lg border border-border/50 bg-muted/30 p-4"
      >
        <AnimatePresence initial={false}>
          {messages.map((msg, i) => (
            <motion.div
              key={i}
              initial={{ opacity: 0, x: -8 }}
              animate={{ opacity: 1, x: 0 }}
              transition={{ duration: 0.2 }}
              className="flex items-start gap-2 py-0.5"
            >
              <span className="mt-0.5 select-none font-mono text-xs text-muted-foreground/50">
                &gt;
              </span>
              <span className="font-mono text-xs leading-relaxed text-foreground/80">
                {msg}
              </span>
            </motion.div>
          ))}
        </AnimatePresence>

        {!failed && messages.length > 0 && (
          <span className="ml-4 inline-block h-3.5 w-1.5 animate-pulse bg-foreground/40" />
        )}
      </div>

      {failed ? (
        <Button variant="outline" onClick={onRetry} className="gap-2">
          <RotateCcw className="h-3.5 w-3.5" />
          Retry
        </Button>
      ) : (
        <div className="w-full space-y-3">
          <Skeleton className="h-4 w-3/4" />
          <Skeleton className="h-4 w-1/2" />
          <Skeleton className="h-4 w-5/6" />
        </div>
      )}

      {failed && (
        <div className="flex items-center gap-2 text-xs text-destructive">
          <AlertCircle className="h-3.5 w-3.5" />
          {error}
        </div>
      )}

      {!failed && (
        <div className="flex items-center gap-2 text-xs text-muted-foreground/50">
          <Loader2 className="h-3 w-3 animate-spin" />
          This may take 30–60 seconds
        </div>
      )}
    </motion.div>
  );
}
