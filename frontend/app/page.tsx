"use client";

import { useCallback, useState } from "react";
import { AnimatePresence, motion } from "framer-motion";
import { AppHeader } from "@/components/app-header";
import { SearchHero } from "@/components/exploration/search-hero";
import { ProgressView } from "@/components/exploration/progress-view";
import { ReportViewer } from "@/components/exploration/report-viewer";
import { MonitoringView } from "@/components/monitoring/monitoring-view";
import { startExploration, getExplorationStatus } from "@/lib/api";
import type { ExplorationReport } from "@/types";

type ExplorationPhase = "idle" | "loading" | "completed" | "failed";

export default function Home() {
  const [activeTab, setActiveTab] = useState("explore");

  // Exploration state machine
  const [phase, setPhase] = useState<ExplorationPhase>("idle");
  const [taskId, setTaskId] = useState<string | null>(null);
  const [report, setReport] = useState<ExplorationReport | null>(null);
  const [lastTopic, setLastTopic] = useState("");

  const handleSearch = async (topic: string) => {
    try {
      setLastTopic(topic);
      setPhase("loading");
      setReport(null);
      const { task_id } = await startExploration(topic);
      setTaskId(task_id);
    } catch {
      setPhase("failed");
    }
  };

  const handleStreamComplete = useCallback(async () => {
    if (!taskId) return;
    try {
      const status = await getExplorationStatus(taskId);
      if (status.result) {
        setReport(status.result);
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
    setReport(null);
  };

  return (
    <div className="flex min-h-screen flex-col bg-background">
      <AppHeader activeTab={activeTab} onTabChange={setActiveTab} />

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
                <ProgressView
                  taskId={taskId}
                  onComplete={handleStreamComplete}
                  onRetry={handleRetry}
                />
              )}

              {phase === "failed" && !taskId && (
                <div className="flex min-h-[calc(100vh-3.5rem)] items-center justify-center">
                  <div className="text-center">
                    <p className="mb-4 text-sm text-muted-foreground">
                      Failed to start exploration. Please try again.
                    </p>
                    <button
                      onClick={resetToIdle}
                      className="text-sm font-medium underline underline-offset-4"
                    >
                      Back to search
                    </button>
                  </div>
                </div>
              )}

              {phase === "completed" && report && (
                <ReportViewer report={report} onNewSearch={resetToIdle} />
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
