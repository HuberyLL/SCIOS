"use client";

import { useCallback, useMemo } from "react";
import {
  ReactFlow,
  Controls,
  type Node,
  type Edge,
  MarkerType,
} from "@xyflow/react";
import dagre from "dagre";
import "@xyflow/react/dist/style.css";

import { TechTreeNode, type TechNodeData, TYPE_CONFIG, importanceToWidth } from "./tech-tree-nodes";
import type { TechTree, TechTreeRelation, TechTreeNodeType } from "@/types";

/* ------------------------------------------------------------------ */
/* Props                                                               */
/* ------------------------------------------------------------------ */

interface TechTreeViewProps {
  data: TechTree;
  onPaperClick: (paperId: string) => void;
}

/* ------------------------------------------------------------------ */
/* Constants                                                           */
/* ------------------------------------------------------------------ */

const BASE_NODE_HEIGHT = 52;

const EDGE_COLORS: Record<TechTreeRelation, string> = {
  evolves_from: "#e76f51",
  extends: "#2a9d8f",
  alternative_to: "#e9c46a",
  inspires: "#7c3aed",
};

const RELATION_LABELS: Record<TechTreeRelation, string> = {
  evolves_from: "Evolves from",
  extends: "Extends",
  alternative_to: "Alternative",
  inspires: "Inspires",
};

const nodeTypes = { techTree: TechTreeNode };

/* ------------------------------------------------------------------ */
/* Layout                                                              */
/* ------------------------------------------------------------------ */

function layoutGraph(techTree: TechTree) {
  const YEAR_RANK_SEP = 120;
  const YEAR_MARGIN = 40;
  const H_MIN_GAP = 30;

  /* --- Step 1: Run dagre for X (horizontal) positioning --- */
  const g = new dagre.graphlib.Graph();
  g.setDefaultEdgeLabel(() => ({}));
  g.setGraph({
    rankdir: "TB",
    nodesep: 80,
    ranksep: 100,
    marginx: 40,
    marginy: 40,
  });

  for (const node of techTree.nodes) {
    const w = importanceToWidth(node.importance ?? 0.5);
    g.setNode(node.node_id, { width: w, height: BASE_NODE_HEIGHT });
  }
  for (const edge of techTree.edges) {
    g.setEdge(edge.source, edge.target);
  }

  dagre.layout(g);

  /* --- Step 2: Year-based Y correction --- */
  type NLayout = { id: string; year: number; dagreX: number; width: number };
  const layouts: NLayout[] = techTree.nodes.map((n) => {
    const pos = g.node(n.node_id);
    return {
      id: n.node_id,
      year: n.year ?? 9999,
      dagreX: pos?.x ?? 0,
      width: importanceToWidth(n.importance ?? 0.5),
    };
  });

  const uniqueYears = [...new Set(layouts.map((l) => l.year))].sort(
    (a, b) => a - b,
  );
  const yearToY = new Map<number, number>();
  uniqueYears.forEach((yr, idx) => {
    yearToY.set(yr, YEAR_MARGIN + idx * YEAR_RANK_SEP);
  });

  /* --- Step 3: Resolve horizontal overlaps within each year band --- */
  const yearGroups = new Map<number, NLayout[]>();
  for (const l of layouts) {
    if (!yearGroups.has(l.year)) yearGroups.set(l.year, []);
    yearGroups.get(l.year)!.push(l);
  }

  const correctedX = new Map<string, number>();
  for (const [, group] of yearGroups) {
    group.sort((a, b) => a.dagreX - b.dagreX);
    for (let i = 0; i < group.length; i++) {
      if (i === 0) {
        correctedX.set(group[i].id, group[i].dagreX);
        continue;
      }
      const prev = group[i - 1];
      const curr = group[i];
      const prevX = correctedX.get(prev.id)!;
      const minX = prevX + prev.width / 2 + H_MIN_GAP + curr.width / 2;
      correctedX.set(curr.id, Math.max(curr.dagreX, minX));
    }
  }

  /* --- Step 4: Build final nodes & edges --- */
  const nodes: Node[] = techTree.nodes.map((n) => {
    const w = importanceToWidth(n.importance ?? 0.5);
    const year = n.year ?? 9999;
    const x = correctedX.get(n.node_id) ?? 0;
    const y = yearToY.get(year) ?? 0;
    return {
      id: n.node_id,
      type: "techTree",
      position: { x: x - w / 2, y },
      data: {
        label: n.label,
        nodeType: n.node_type,
        year: n.year,
        description: n.description,
        importance: n.importance ?? 0.5,
        depth: n.depth ?? 0,
        paperIds: n.representative_paper_ids,
        isNew: n.is_new,
      } satisfies TechNodeData,
    };
  });

  /* --- Step 5: Flip edges that violate temporal direction --- */
  const yearMap = new Map(
    techTree.nodes.map((n) => [n.node_id, n.year ?? 9999]),
  );

  const edges: Edge[] = techTree.edges.map((e, i) => {
    const srcYear = yearMap.get(e.source) ?? 9999;
    const tgtYear = yearMap.get(e.target) ?? 9999;
    const flipped = srcYear > tgtYear;
    const color = EDGE_COLORS[e.relation] || "#94a3b8";
    return {
      id: `e-${i}`,
      source: flipped ? e.target : e.source,
      target: flipped ? e.source : e.target,
      type: "default",
      markerEnd: {
        type: MarkerType.ArrowClosed,
        width: 14,
        height: 14,
        color,
      },
      style: { stroke: color, strokeWidth: 2 },
    };
  });

  return { nodes, edges };
}

/* ------------------------------------------------------------------ */
/* Legend panel                                                         */
/* ------------------------------------------------------------------ */

const LEGEND_TYPES: TechTreeNodeType[] = [
  "foundation",
  "breakthrough",
  "incremental",
  "application",
  "survey",
  "unverified",
];

function Legend() {
  return (
    <div className="absolute top-3 right-3 z-10 rounded-lg border bg-background/90 px-3 py-2 text-[10px] shadow-sm backdrop-blur-sm">
      <p className="mb-1.5 font-semibold text-foreground text-[11px]">Node Types</p>
      <div className="space-y-1">
        {LEGEND_TYPES.map((t) => {
          const cfg = TYPE_CONFIG[t];
          const Icon = cfg.icon;
          return (
            <div key={t} className="flex items-center gap-1.5">
              <Icon className={`h-3 w-3 ${cfg.text}`} />
              <span className="text-muted-foreground">{cfg.label}</span>
            </div>
          );
        })}
      </div>
      <div className="mt-2 border-t pt-1.5">
        <p className="mb-1 font-semibold text-foreground text-[11px]">Edges</p>
        <div className="space-y-0.5">
          {(Object.entries(EDGE_COLORS) as [TechTreeRelation, string][]).map(
            ([rel, color]) => (
              <div key={rel} className="flex items-center gap-1.5">
                <div
                  className="h-0.5 w-3 rounded-full"
                  style={{ backgroundColor: color }}
                />
                <span className="text-muted-foreground">
                  {RELATION_LABELS[rel]}
                </span>
              </div>
            ),
          )}
        </div>
      </div>
    </div>
  );
}

/* ------------------------------------------------------------------ */
/* Main view                                                           */
/* ------------------------------------------------------------------ */

export function TechTreeView({ data, onPaperClick }: TechTreeViewProps) {
  const { nodes, edges } = useMemo(() => layoutGraph(data), [data]);

  const handleNodeClick = useCallback(
    (_: React.MouseEvent, node: Node) => {
      const d = node.data as unknown as TechNodeData;
      if (d.paperIds.length > 0) {
        onPaperClick(d.paperIds[0]);
      }
    },
    [onPaperClick],
  );

  if (data.nodes.length === 0) {
    return (
      <div className="flex h-full items-center justify-center text-sm text-muted-foreground">
        No technology evolution data available.
      </div>
    );
  }

  return (
    <div className="relative h-full w-full">
      <Legend />
      <ReactFlow
        nodes={nodes}
        edges={edges}
        onNodeClick={handleNodeClick}
        nodeTypes={nodeTypes}
        nodesDraggable={false}
        nodesConnectable={false}
        nodesFocusable={false}
        edgesFocusable={false}
        elementsSelectable={false}
        panOnDrag
        zoomOnScroll
        fitView
        fitViewOptions={{ padding: 0.15 }}
        minZoom={0.2}
        maxZoom={2}
        proOptions={{ hideAttribution: true }}
      >
        <Controls showInteractive={false} />
      </ReactFlow>
    </div>
  );
}
