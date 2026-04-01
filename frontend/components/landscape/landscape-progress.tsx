"use client";

import { useEffect, useRef } from "react";
import { motion, AnimatePresence } from "framer-motion";
import { Loader2, AlertCircle } from "lucide-react";
import { Progress } from "@/components/ui/progress";
import { Skeleton } from "@/components/ui/skeleton";
import type { TaskStatus } from "@/types";

interface LandscapeProgressProps {
  messages: string[];
  status: TaskStatus | null;
  error: string | null;
}

const STAGE_WEIGHTS: Record<string, number> = {
  plan: 15,
  retriev: 40,
  enrich: 50,
  build: 65,
  graph: 65,
  analyz: 70,
  assembl: 85,
  complet: 100,
};

function estimateProgress(messages: string[]): number {
  if (messages.length === 0) return 5;
  const last = messages[messages.length - 1].toLowerCase();
  for (const [keyword, pct] of Object.entries(STAGE_WEIGHTS)) {
    if (last.includes(keyword)) return pct;
  }
  return Math.min(10 + messages.length * 10, 95);
}

export function LandscapeProgress({ messages, status, error }: LandscapeProgressProps) {
  const scrollRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    scrollRef.current?.scrollTo({
      top: scrollRef.current.scrollHeight,
      behavior: "smooth",
    });
  }, [messages]);

  const progress =
    status === "completed"
      ? 100
      : status === "running" && messages.length === 0
        ? 8
        : estimateProgress(messages);
  const failed = status === "failed";

  return (
    <div className="flex flex-1 flex-col items-center justify-center gap-6 p-8">
      <div className="w-full max-w-2xl text-center">
        <h2 className="mb-2 text-lg font-semibold text-foreground">
          {failed ? "Analysis Failed" : "Building Research Landscape..."}
        </h2>
        <p className="text-sm text-muted-foreground">
          {failed
            ? error ?? "Something went wrong."
            : "Retrieving papers, building tech tree, mapping collaborations, and analyzing gaps."}
        </p>
      </div>

      {!failed && (
        <div className="w-full max-w-2xl space-y-1">
          <Progress value={progress} className="h-1.5" />
          <p className="text-right font-mono text-[11px] text-muted-foreground/60">
            {progress}%
          </p>
        </div>
      )}

      <div
        ref={scrollRef}
        className="w-full max-w-2xl max-h-64 overflow-y-auto rounded-lg border border-border/50 bg-muted/30 p-4"
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

      {!failed && (
        <div className="w-full max-w-2xl space-y-3">
          <Skeleton className="h-4 w-3/4" />
          <Skeleton className="h-4 w-1/2" />
          <Skeleton className="h-4 w-5/6" />
        </div>
      )}

      {failed && error && (
        <div className="flex items-center gap-2 text-xs text-destructive">
          <AlertCircle className="h-3.5 w-3.5" />
          {error}
        </div>
      )}

      {!failed && (
        <div className="flex items-center gap-2 text-xs text-muted-foreground/50">
          <Loader2 className="h-3 w-3 animate-spin" />
          This may take 60–120 seconds
        </div>
      )}
    </div>
  );
}
