"use client";

import { Suspense, useCallback, useEffect, useState } from "react";
import { useSearchParams } from "next/navigation";
import { AnimatePresence, motion } from "framer-motion";
import { AppHeader } from "@/components/app-header";
import { SearchHero } from "@/components/exploration/search-hero";
import { LandscapeProgress } from "@/components/landscape/landscape-progress";
import { LandscapeBoard } from "@/components/landscape/landscape-board";
import { MonitoringView } from "@/components/monitoring/monitoring-view";
import { startLandscape, getLandscapeStatus } from "@/lib/api";
import type { DynamicResearchLandscape } from "@/types";

type LandscapePhase = "idle" | "loading" | "completed" | "failed";

function HomeContent() {
  const searchParams = useSearchParams();
  const tab = searchParams.get("tab") || "explore";

  const [activeTab, setActiveTab] = useState(tab);

  useEffect(() => {
    setActiveTab(tab);
  }, [tab]);

  const [phase, setPhase] = useState<LandscapePhase>("idle");
  const [taskId, setTaskId] = useState<string | null>(null);
  const [landscape, setLandscape] = useState<DynamicResearchLandscape | null>(null);
  const [lastTopic, setLastTopic] = useState("");

  const handleSearch = async (topic: string) => {
    try {
      setLastTopic(topic);
      setPhase("loading");
      setLandscape(null);
      const { task_id } = await startLandscape(topic);
      setTaskId(task_id);
    } catch {
      setPhase("failed");
    }
  };

  const handleStreamComplete = useCallback(async () => {
    if (!taskId) return;
    try {
      const status = await getLandscapeStatus(taskId);
      if (status.result) {
        setLandscape(status.result);
        setPhase("completed");
      } else {
        setPhase("failed");
      }
    } catch {
      setPhase("failed");
    }
  }, [taskId]);

  const handleRetry = () => {
    if (lastTopic) handleSearch(lastTopic);
    else resetToIdle();
  };

  const resetToIdle = () => {
    setPhase("idle");
    setTaskId(null);
    setLandscape(null);
  };

  useEffect(() => {
    if (phase !== "loading" || !taskId) return;

    let cancelled = false;
    let timer: ReturnType<typeof setTimeout> | null = null;

    const pollStatus = async () => {
      try {
        const status = await getLandscapeStatus(taskId);
        if (cancelled) return;

        if (status.status === "completed" && status.result) {
          setLandscape(status.result);
          setPhase("completed");
          return;
        }

        if (status.status === "failed") {
          setPhase("failed");
          return;
        }
      } catch {
        // Keep retrying while SSE may still deliver live updates.
      }

      if (!cancelled) {
        timer = setTimeout(pollStatus, 2500);
      }
    };

    timer = setTimeout(pollStatus, 2500);
    return () => {
      cancelled = true;
      if (timer) clearTimeout(timer);
    };
  }, [phase, taskId]);

  return (
    <div className="flex min-h-screen flex-col bg-background">
      <AppHeader />

      <main className="flex-1">
        <AnimatePresence mode="wait">
          {activeTab === "explore" ? (
            <motion.div
              key="explore"
              initial={{ opacity: 0 }}
              animate={{ opacity: 1 }}
              exit={{ opacity: 0 }}
              transition={{ duration: 0.2 }}
            >
              {phase === "idle" && <SearchHero onSearch={handleSearch} />}

              {phase === "loading" && taskId && (
                <LandscapeProgress
                  key={taskId}
                  taskId={taskId}
                  onComplete={handleStreamComplete}
                  onRetry={handleRetry}
                />
              )}

              {phase === "failed" && (
                <div className="flex min-h-[calc(100vh-3.5rem)] items-center justify-center">
                  <div className="text-center">
                    <p className="mb-4 text-sm text-muted-foreground">
                      Landscape analysis failed. Please try again.
                    </p>
                    <button
                      onClick={handleRetry}
                      className="text-sm font-medium underline underline-offset-4"
                    >
                      Retry
                    </button>
                  </div>
                </div>
              )}

              {phase === "completed" && landscape && (
                <LandscapeBoard landscape={landscape} onNewSearch={resetToIdle} />
              )}
            </motion.div>
          ) : (
            <motion.div
              key="monitor"
              initial={{ opacity: 0 }}
              animate={{ opacity: 1 }}
              exit={{ opacity: 0 }}
              transition={{ duration: 0.2 }}
            >
              <MonitoringView />
            </motion.div>
          )}
        </AnimatePresence>
      </main>
    </div>
  );
}

export default function Home() {
  return (
    <Suspense>
      <HomeContent />
    </Suspense>
  );
}
