"use client";

import { useCallback, useMemo, useState } from "react";
import dynamic from "next/dynamic";
import { motion } from "framer-motion";
import {
  GitBranch,
  Network,
  AlertTriangle,
  FileText,
  Clock,
} from "lucide-react";
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs";
import { Badge } from "@/components/ui/badge";
import { ResearchGapsView } from "./research-gaps-view";
import { PaperDetailPanel } from "./paper-detail-panel";
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
}

const fadeUp = {
  initial: { opacity: 0, y: 16 },
  animate: { opacity: 1, y: 0 },
};

export function LandscapeBoard({ landscape }: LandscapeBoardProps) {
  const [selectedPaperId, setSelectedPaperId] = useState<string | null>(null);

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

  const { meta, tech_tree, collaboration_network, research_gaps } = landscape;

  const generatedDate = meta.generated_at
    ? new Date(meta.generated_at).toLocaleDateString("en-US", {
        year: "numeric",
        month: "short",
        day: "numeric",
        hour: "2-digit",
        minute: "2-digit",
      })
    : "";

  return (
    <motion.div
      initial="initial"
      animate="animate"
      variants={fadeUp}
      transition={{ duration: 0.4 }}
      className="flex flex-1 flex-col gap-4 overflow-hidden px-6 py-4"
    >
      {/* Header */}
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

      {/* Tab views */}
      <Tabs defaultValue="tech-tree" className="flex min-h-0 flex-1 flex-col">
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

        <TabsContent value="tech-tree" className="mt-3 flex-1">
          <TechTreeView data={tech_tree} onPaperClick={handlePaperClick} />
        </TabsContent>

        <TabsContent value="collaboration" className="mt-3 flex-1">
          <CollaborationGraph
            data={collaboration_network}
            onScholarClick={handleScholarClick}
          />
        </TabsContent>

        <TabsContent value="gaps" className="mt-3 flex-1 overflow-auto">
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
