"use client";

import { useCallback, useMemo, useState } from "react";
import dynamic from "next/dynamic";
import { motion, AnimatePresence } from "framer-motion";
import {
  GitBranch,
  Network,
  Table2,
  AlertTriangle,
  FileText,
  Clock,
  Search,
  Bell,
  BellOff,
  ArrowDownToLine,
  Loader2,
} from "lucide-react";
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { ComparisonMatrix } from "./comparison-matrix";
import { ResearchGapsView } from "./research-gaps-view";
import { PaperDetailPanel } from "./paper-detail-panel";
import { useLandscapeMonitor } from "@/hooks/use-landscape-monitor";
import { mergeLandscapeIncrement } from "@/lib/landscape-merge";
import type { DynamicResearchLandscape, PaperResult } from "@/types";

const TechTreeView = dynamic(
  () => import("./tech-tree-view").then((m) => ({ default: m.TechTreeView })),
  { ssr: false },
);
const CollaborationGraph = dynamic(
  () => import("./collaboration-graph").then((m) => ({ default: m.CollaborationGraph })),
  { ssr: false },
);

interface LandscapeBoardProps {
  landscape: DynamicResearchLandscape;
  onNewSearch: () => void;
}

const fadeUp = {
  initial: { opacity: 0, y: 16 },
  animate: { opacity: 1, y: 0 },
};

export function LandscapeBoard({ landscape: initialLandscape, onNewSearch }: LandscapeBoardProps) {
  const [landscape, setLandscape] = useState(initialLandscape);
  const [selectedPaperId, setSelectedPaperId] = useState<string | null>(null);

  const monitor = useLandscapeMonitor(landscape.meta.topic);

  const paperMap = useMemo(() => {
    const map = new Map<string, PaperResult>();
    for (const p of landscape.papers) {
      map.set(p.paper_id, p);
    }
    return map;
  }, [landscape.papers]);

  const selectedPaper = selectedPaperId ? (paperMap.get(selectedPaperId) ?? null) : null;

  const handlePaperClick = useCallback((paperId: string) => {
    setSelectedPaperId(paperId);
  }, []);

  const handleScholarClick = useCallback((paperIds: string[]) => {
    if (paperIds.length > 0) {
      setSelectedPaperId(paperIds[0]);
    }
  }, []);

  const handleClosePaper = useCallback(() => {
    setSelectedPaperId(null);
  }, []);

  const handleApplyUpdates = useCallback(() => {
    let merged = landscape;
    for (const entry of monitor.pendingIncrements) {
      merged = mergeLandscapeIncrement(merged, entry.increment);
    }
    setLandscape(merged);
    monitor.clearIncrements();
  }, [landscape, monitor]);

  const { meta, tech_tree, collaboration_network, comparison_matrix, research_gaps } = landscape;

  const generatedDate = meta.generated_at
    ? new Date(meta.generated_at).toLocaleDateString("en-US", {
        year: "numeric",
        month: "short",
        day: "numeric",
        hour: "2-digit",
        minute: "2-digit",
      })
    : "";

  const pendingCount = monitor.pendingIncrements.length;
  const pendingPaperCount = monitor.pendingIncrements.reduce(
    (sum, entry) => sum + entry.increment.new_papers.length,
    0,
  );

  return (
    <motion.div
      initial="initial"
      animate="animate"
      variants={fadeUp}
      transition={{ duration: 0.4 }}
      className="mx-auto flex max-w-7xl flex-col gap-4 px-6 py-6"
    >
      {/* Header */}
      <div className="flex items-start justify-between gap-4">
        <div className="space-y-1">
          <h1 className="text-xl font-bold tracking-tight sm:text-2xl">
            {meta.topic}
          </h1>
          <div className="flex flex-wrap items-center gap-2 text-xs text-muted-foreground">
            <span className="inline-flex items-center gap-1">
              <FileText className="h-3 w-3" />
              {meta.paper_count} papers
            </span>
            <span className="inline-flex items-center gap-1">
              <GitBranch className="h-3 w-3" />
              {tech_tree.nodes.length} tech nodes
            </span>
            <span className="inline-flex items-center gap-1">
              <Network className="h-3 w-3" />
              {collaboration_network.nodes.length} scholars
            </span>
            {generatedDate && (
              <span className="inline-flex items-center gap-1">
                <Clock className="h-3 w-3" />
                {generatedDate}
              </span>
            )}
          </div>
        </div>

        <div className="flex items-center gap-2 shrink-0">
          {monitor.loading ? (
            <Button variant="outline" size="sm" disabled className="gap-1.5">
              <Loader2 className="h-3.5 w-3.5 animate-spin" />
            </Button>
          ) : monitor.subscribed ? (
            <Button
              variant="outline"
              size="sm"
              onClick={monitor.unsubscribe}
              className="gap-1.5 text-amber-600 border-amber-200 hover:bg-amber-50"
            >
              <BellOff className="h-3.5 w-3.5" />
              Unsubscribe
            </Button>
          ) : (
            <Button
              variant="outline"
              size="sm"
              onClick={monitor.subscribe}
              className="gap-1.5"
            >
              <Bell className="h-3.5 w-3.5" />
              Subscribe
            </Button>
          )}
          <Button variant="outline" size="sm" onClick={onNewSearch} className="gap-1.5">
            <Search className="h-3.5 w-3.5" />
            New Search
          </Button>
        </div>
      </div>

      {/* Pending increments notification bar */}
      <AnimatePresence>
        {pendingCount > 0 && (
          <motion.div
            initial={{ opacity: 0, height: 0 }}
            animate={{ opacity: 1, height: "auto" }}
            exit={{ opacity: 0, height: 0 }}
            className="flex items-center justify-between rounded-lg border border-emerald-200 bg-emerald-50 px-4 py-2.5 dark:border-emerald-800 dark:bg-emerald-950/30"
          >
            <div className="flex items-center gap-2 text-sm text-emerald-700 dark:text-emerald-300">
              <ArrowDownToLine className="h-4 w-4" />
              <span>
                <strong>{pendingCount}</strong> new update{pendingCount > 1 ? "s" : ""} available
                {pendingPaperCount > 0 && (
                  <span className="text-emerald-600 dark:text-emerald-400">
                    {" "}({pendingPaperCount} new paper{pendingPaperCount > 1 ? "s" : ""})
                  </span>
                )}
              </span>
            </div>
            <Button
              size="sm"
              variant="default"
              onClick={handleApplyUpdates}
              className="gap-1.5 bg-emerald-600 text-white hover:bg-emerald-700"
            >
              <ArrowDownToLine className="h-3.5 w-3.5" />
              Apply Updates
            </Button>
          </motion.div>
        )}
      </AnimatePresence>

      {/* Tab views */}
      <Tabs defaultValue="tech-tree" className="flex-1">
        <TabsList className="w-full justify-start">
          <TabsTrigger value="tech-tree" className="gap-1.5">
            <GitBranch className="h-3.5 w-3.5" />
            Tech Tree
            {tech_tree.nodes.filter((n) => n.is_new).length > 0 && (
              <Badge className="ml-1 bg-emerald-500 px-1 py-0 text-[9px] text-white">
                {tech_tree.nodes.filter((n) => n.is_new).length}
              </Badge>
            )}
          </TabsTrigger>
          <TabsTrigger value="collaboration" className="gap-1.5">
            <Network className="h-3.5 w-3.5" />
            Collaboration
          </TabsTrigger>
          <TabsTrigger value="comparison" className="gap-1.5">
            <Table2 className="h-3.5 w-3.5" />
            Comparison
          </TabsTrigger>
          <TabsTrigger value="gaps" className="gap-1.5">
            <AlertTriangle className="h-3.5 w-3.5" />
            Gaps
            {research_gaps.gaps.filter((g) => g.impact === "high").length > 0 && (
              <Badge variant="destructive" className="ml-1 px-1 py-0 text-[9px]">
                {research_gaps.gaps.filter((g) => g.impact === "high").length}
              </Badge>
            )}
          </TabsTrigger>
        </TabsList>

        <TabsContent value="tech-tree" className="mt-3 h-[calc(100vh-16rem)]">
          <TechTreeView data={tech_tree} onPaperClick={handlePaperClick} />
        </TabsContent>

        <TabsContent value="collaboration" className="mt-3 h-[calc(100vh-16rem)]">
          <CollaborationGraph
            data={collaboration_network}
            onScholarClick={handleScholarClick}
          />
        </TabsContent>

        <TabsContent value="comparison" className="mt-3 h-[calc(100vh-16rem)]">
          <ComparisonMatrix data={comparison_matrix} onPaperClick={handlePaperClick} />
        </TabsContent>

        <TabsContent value="gaps" className="mt-3 h-[calc(100vh-16rem)] overflow-auto">
          <ResearchGapsView data={research_gaps} onPaperClick={handlePaperClick} />
        </TabsContent>
      </Tabs>

      {/* Paper detail side panel */}
      <PaperDetailPanel
        paper={selectedPaper}
        open={selectedPaper !== null}
        onClose={handleClosePaper}
      />
    </motion.div>
  );
}
