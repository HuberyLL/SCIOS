"use client";

import { useCallback, useEffect, useMemo } from "react";
import {
  ReactFlow,
  Controls,
  MiniMap,
  Background,
  BackgroundVariant,
  useNodesState,
  useEdgesState,
  type Node,
  type Edge,
  MarkerType,
} from "@xyflow/react";
import dagre from "dagre";
import "@xyflow/react/dist/style.css";

import { TechTreeNode, type TechNodeData } from "./tech-tree-nodes";
import type { TechTree, TechTreeRelation } from "@/types";

interface TechTreeViewProps {
  data: TechTree;
  onPaperClick: (paperId: string) => void;
}

const NODE_WIDTH = 200;
const NODE_HEIGHT = 80;

const EDGE_COLORS: Record<TechTreeRelation, string> = {
  evolves_from: "hsl(var(--chart-1))",
  extends: "hsl(var(--chart-2))",
  alternative_to: "hsl(var(--chart-3))",
  inspires: "hsl(var(--chart-4))",
};

const nodeTypes = { techTree: TechTreeNode };

function layoutGraph(techTree: TechTree) {
  const g = new dagre.graphlib.Graph();
  g.setDefaultEdgeLabel(() => ({}));
  g.setGraph({ rankdir: "TB", nodesep: 50, ranksep: 80, marginx: 20, marginy: 20 });

  for (const node of techTree.nodes) {
    g.setNode(node.node_id, { width: NODE_WIDTH, height: NODE_HEIGHT });
  }
  for (const edge of techTree.edges) {
    g.setEdge(edge.source, edge.target);
  }

  dagre.layout(g);

  const nodes: Node[] = techTree.nodes.map((n) => {
    const pos = g.node(n.node_id);
    return {
      id: n.node_id,
      type: "techTree",
      position: {
        x: (pos?.x ?? 0) - NODE_WIDTH / 2,
        y: (pos?.y ?? 0) - NODE_HEIGHT / 2,
      },
      data: {
        label: n.label,
        nodeType: n.node_type,
        year: n.year,
        description: n.description,
        paperIds: n.representative_paper_ids,
        isNew: n.is_new,
      } satisfies TechNodeData,
    };
  });

  const edges: Edge[] = techTree.edges.map((e, i) => ({
    id: `e-${i}`,
    source: e.source,
    target: e.target,
    label: e.label || e.relation.replace(/_/g, " "),
    labelStyle: { fontSize: 10, fill: "hsl(var(--muted-foreground))" },
    animated: e.relation === "inspires",
    markerEnd: { type: MarkerType.ArrowClosed, width: 16, height: 16 },
    style: { stroke: EDGE_COLORS[e.relation] || "hsl(var(--border))", strokeWidth: 1.5 },
  }));

  return { nodes, edges };
}

export function TechTreeView({ data, onPaperClick }: TechTreeViewProps) {
  const { nodes: initialNodes, edges: initialEdges } = useMemo(
    () => layoutGraph(data),
    [data],
  );

  const [nodes, setNodes, onNodesChange] = useNodesState(initialNodes);
  const [edges, setEdges, onEdgesChange] = useEdgesState(initialEdges);

  useEffect(() => {
    const { nodes: n, edges: e } = layoutGraph(data);
    setNodes(n);
    setEdges(e);
  }, [data, setNodes, setEdges]);

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
    <div className="h-full w-full">
      <ReactFlow
        nodes={nodes}
        edges={edges}
        onNodesChange={onNodesChange}
        onEdgesChange={onEdgesChange}
        onNodeClick={handleNodeClick}
        nodeTypes={nodeTypes}
        fitView
        fitViewOptions={{ padding: 0.2 }}
        minZoom={0.3}
        maxZoom={2}
        proOptions={{ hideAttribution: true }}
      >
        <Background variant={BackgroundVariant.Dots} gap={16} size={1} />
        <Controls showInteractive={false} />
        <MiniMap
          nodeStrokeWidth={2}
          pannable
          zoomable
          className="bg-background/80! border-border/50!"
        />
      </ReactFlow>
    </div>
  );
}
