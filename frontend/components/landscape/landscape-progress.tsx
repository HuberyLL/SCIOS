"use client";

import { useEffect, useRef, useState } from "react";
import { motion, AnimatePresence } from "framer-motion";
import {
  Loader2,
  AlertCircle,
  Check,
  Circle,
  SkipForward,
  ChevronDown,
} from "lucide-react";
import { Progress } from "@/components/ui/progress";
import { Skeleton } from "@/components/ui/skeleton";
import type { PipelineStage, TaskStatus } from "@/types";

interface LandscapeProgressProps {
  messages: string[];
  stages: PipelineStage[];
  progressPct: number;
  status: TaskStatus | null;
  error: string | null;
}

// ---------------------------------------------------------------------------
// Stage status icon
// ---------------------------------------------------------------------------

function StageIcon({ status }: { status: PipelineStage["status"] }) {
  switch (status) {
    case "running":
      return <Loader2 className="h-4 w-4 animate-spin text-primary" />;
    case "completed":
      return <Check className="h-4 w-4 text-emerald-500" />;
    case "failed":
      return <AlertCircle className="h-4 w-4 text-destructive" />;
    case "skipped":
      return <SkipForward className="h-4 w-4 text-muted-foreground/50" />;
    default:
      return <Circle className="h-3.5 w-3.5 text-muted-foreground/30" />;
  }
}

// ---------------------------------------------------------------------------
// Single stage row
// ---------------------------------------------------------------------------

function StageRow({ stage }: { stage: PipelineStage }) {
  const isActive = stage.status === "running";
  const isDone = stage.status === "completed" || stage.status === "failed";
  const hasMessages = stage.messages.length > 0;
  const [expanded, setExpanded] = useState(false);

  useEffect(() => {
    if (isActive) setExpanded(true);
    if (isDone) {
      const t = setTimeout(() => setExpanded(false), 600);
      return () => clearTimeout(t);
    }
  }, [isActive, isDone]);

  const detailSummary = stage.detail
    ? Object.entries(stage.detail)
        .filter(([, v]) => typeof v === "number" || typeof v === "string")
        .map(([k, v]) => `${k.replace(/_/g, " ")}: ${v}`)
        .join("  ·  ")
    : null;

  return (
    <div className="relative pl-7">
      {/* Timeline connector line */}
      <div className="absolute left-[7px] top-0 bottom-0 w-px bg-border" />

      {/* Status icon (overlays the line) */}
      <div className="absolute left-0 top-1 flex h-4 w-4 items-center justify-center rounded-full bg-background">
        <StageIcon status={stage.status} />
      </div>

      <div className="pb-4">
        {/* Header row: clickable to toggle */}
        <button
          type="button"
          onClick={() => hasMessages && setExpanded((e) => !e)}
          className="flex w-full items-center gap-2 text-left"
        >
          <span
            className={`text-sm font-medium ${
              isActive
                ? "text-foreground"
                : isDone
                  ? "text-foreground/80"
                  : "text-muted-foreground/50"
            }`}
          >
            {stage.label}
          </span>

          {stage.elapsed_s > 0 && (
            <span className="font-mono text-[11px] text-muted-foreground/60">
              {stage.elapsed_s.toFixed(1)}s
            </span>
          )}

          {hasMessages && (
            <ChevronDown
              className={`ml-auto h-3.5 w-3.5 text-muted-foreground/40 transition-transform ${
                expanded ? "rotate-180" : ""
              }`}
            />
          )}
        </button>

        {/* Detail summary chips */}
        {detailSummary && isDone && (
          <p className="mt-0.5 text-[11px] text-muted-foreground/60">
            {detailSummary}
          </p>
        )}

        {/* Expandable sub-messages */}
        <AnimatePresence initial={false}>
          {expanded && hasMessages && (
            <motion.div
              initial={{ height: 0, opacity: 0 }}
              animate={{ height: "auto", opacity: 1 }}
              exit={{ height: 0, opacity: 0 }}
              transition={{ duration: 0.2 }}
              className="overflow-hidden"
            >
              <div className="mt-1.5 space-y-0.5 rounded-md border border-border/40 bg-muted/20 p-2">
                {stage.messages.map((msg, i) => (
                  <div
                    key={i}
                    className="flex items-start gap-1.5"
                  >
                    <span className="mt-0.5 select-none font-mono text-[10px] text-muted-foreground/40">
                      &gt;
                    </span>
                    <span className="font-mono text-[11px] leading-relaxed text-foreground/70">
                      {msg}
                    </span>
                  </div>
                ))}
                {isActive && (
                  <span className="ml-3 inline-block h-3 w-1 animate-pulse bg-foreground/30" />
                )}
              </div>
            </motion.div>
          )}
        </AnimatePresence>
      </div>
    </div>
  );
}

// ---------------------------------------------------------------------------
// Main progress component
// ---------------------------------------------------------------------------

export function LandscapeProgress({
  stages,
  progressPct,
  status,
  error,
}: LandscapeProgressProps) {
  const scrollRef = useRef<HTMLDivElement>(null);
  const failed = status === "failed";

  // Auto-scroll when active stage changes
  useEffect(() => {
    const activeIdx = stages.findIndex((s) => s.status === "running");
    if (activeIdx >= 0 && scrollRef.current) {
      const items = scrollRef.current.querySelectorAll("[data-stage]");
      items[activeIdx]?.scrollIntoView({ behavior: "smooth", block: "nearest" });
    }
  }, [stages]);

  const displayPct = status === "completed" ? 100 : progressPct;

  return (
    <div className="flex flex-1 flex-col items-center justify-center gap-5 p-8">
      {/* Title */}
      <div className="w-full max-w-lg text-center">
        <h2 className="mb-1 text-lg font-semibold text-foreground">
          {failed ? "Analysis Failed" : "Building Research Landscape"}
        </h2>
        <p className="text-xs text-muted-foreground">
          {failed
            ? error ?? "Something went wrong."
            : "Multi-agent pipeline is analysing papers, scholars, and research gaps."}
        </p>
      </div>

      {/* Overall progress bar */}
      {!failed && (
        <div className="w-full max-w-lg space-y-1">
          <Progress value={displayPct} className="h-1.5" />
          <p className="text-right font-mono text-[11px] text-muted-foreground/60">
            {displayPct}%
          </p>
        </div>
      )}

      {/* Pipeline Stepper */}
      <div
        ref={scrollRef}
        className="w-full max-w-lg max-h-[420px] overflow-y-auto rounded-lg border border-border/50 bg-muted/10 p-4"
      >
        {stages.map((stage) => (
          <div key={stage.id} data-stage={stage.id}>
            <StageRow stage={stage} />
          </div>
        ))}
      </div>

      {/* Loading skeleton */}
      {!failed && status === "running" && (
        <div className="w-full max-w-lg space-y-2.5">
          <Skeleton className="h-3.5 w-3/4" />
          <Skeleton className="h-3.5 w-1/2" />
          <Skeleton className="h-3.5 w-5/6" />
        </div>
      )}

      {/* Error display */}
      {failed && error && (
        <div className="flex items-center gap-2 text-xs text-destructive">
          <AlertCircle className="h-3.5 w-3.5" />
          {error}
        </div>
      )}
    </div>
  );
}
