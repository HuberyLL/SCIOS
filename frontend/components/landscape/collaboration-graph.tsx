"use client";

import { useMemo, useCallback, useRef } from "react";
import ReactEChartsCore from "echarts-for-react/lib/core";
import * as echarts from "echarts/core";
import { GraphChart } from "echarts/charts";
import { TooltipComponent, LegendComponent } from "echarts/components";
import { CanvasRenderer } from "echarts/renderers";
import type { CollaborationNetwork, PaperResult, ScholarNode } from "@/types";

echarts.use([GraphChart, TooltipComponent, LegendComponent, CanvasRenderer]);

interface CollaborationGraphProps {
  data: CollaborationNetwork;
  paperMap: Map<string, PaperResult>;
  onScholarClick: (scholar: ScholarNode) => void;
}

function clamp(value: number, min: number, max: number) {
  return Math.min(Math.max(value, min), max);
}

export function CollaborationGraph({ data, paperMap, onScholarClick }: CollaborationGraphProps) {
  const chartRef = useRef<ReactEChartsCore>(null);

  const scholarMap = useMemo(() => {
    const m = new Map<string, ScholarNode>();
    for (const n of data.nodes) m.set(n.scholar_id, n);
    return m;
  }, [data.nodes]);

  const option = useMemo(() => {
    if (data.nodes.length === 0) return null;

    const maxCitations = Math.max(...data.nodes.map((n) => n.citation_count), 1);
    const maxWeight = Math.max(...data.edges.map((e) => e.weight), 1);

    const nameById = new Map<string, string>();
    for (const n of data.nodes) nameById.set(n.scholar_id, n.name);

    const nodes = data.nodes.map((n) => ({
      id: n.scholar_id,
      name: n.name,
      symbolSize: clamp((n.citation_count / maxCitations) * 50, 12, 60),
      value: n.citation_count,
      category: n.is_new ? 1 : 0,
      itemStyle: n.is_new
        ? {
            borderColor: "hsl(142, 71%, 45%)",
            borderWidth: 3,
            shadowColor: "hsla(142, 71%, 45%, 0.5)",
            shadowBlur: 12,
          }
        : undefined,
      tooltip: {
        formatter: () => {
          const aff = n.affiliations.length > 0 ? n.affiliations.join(", ") : "N/A";
          return [
            `<strong>${n.name}</strong>`,
            `Affiliations: ${aff}`,
            n.h_index > 0 ? `h-index: ${n.h_index}` : "",
            `Papers: ${n.paper_count}`,
            `Citations: ${n.citation_count.toLocaleString()}`,
            n.is_new ? '<span style="color:#22c55e">● New Scholar</span>' : "",
          ]
            .filter(Boolean)
            .join("<br/>");
        },
      },
      _scholarId: n.scholar_id,
    }));

    const links = data.edges.map((e) => {
      const srcName = nameById.get(e.source) ?? e.source;
      const tgtName = nameById.get(e.target) ?? e.target;

      const sharedTitles = e.shared_paper_ids
        .map((pid) => paperMap.get(pid)?.title)
        .filter((t): t is string => t != null);

      return {
        source: e.source,
        target: e.target,
        value: e.weight,
        lineStyle: {
          width: clamp((e.weight / maxWeight) * 5, 0.5, 6),
          opacity: 0.4,
        },
        tooltip: {
          formatter: () => {
            const lines = [
              `<strong>${srcName}</strong> & <strong>${tgtName}</strong>`,
              `Co-authored ${e.weight} paper${e.weight > 1 ? "s" : ""}`,
            ];
            if (sharedTitles.length > 0) {
              const MAX_SHOW = 3;
              const shown = sharedTitles.slice(0, MAX_SHOW);
              lines.push("");
              for (const t of shown) {
                lines.push(`<span style="color:#999">·</span> ${t}`);
              }
              if (sharedTitles.length > MAX_SHOW) {
                lines.push(
                  `<span style="color:#999">  … and ${sharedTitles.length - MAX_SHOW} more</span>`,
                );
              }
            }
            return lines.join("<br/>");
          },
        },
      };
    });

    return {
      tooltip: {
        show: true,
        enterable: true,
        confine: true,
        extraCssText: "max-width:320px; white-space:normal;",
      },
      legend: { show: false },
      series: [
        {
          type: "graph",
          layout: "force",
          roam: true,
          draggable: true,
          force: {
            repulsion: 300,
            edgeLength: [80, 200],
            gravity: 0.1,
          },
          label: {
            show: true,
            position: "bottom",
            fontSize: 10,
            color: "inherit",
          },
          edgeLabel: { show: false },
          categories: [
            { name: "Existing" },
            { name: "New" },
          ],
          data: nodes,
          links,
          emphasis: {
            focus: "adjacency",
            lineStyle: { width: 3 },
          },
          large: data.nodes.length > 200,
        },
      ],
    };
  }, [data, paperMap]);

  const handleClick = useCallback(
    (params: { data?: { _scholarId?: string } }) => {
      const sid = params.data?._scholarId;
      if (!sid) return;
      const scholar = scholarMap.get(sid);
      if (scholar) onScholarClick(scholar);
    },
    [onScholarClick, scholarMap],
  );

  if (data.nodes.length === 0) {
    return (
      <div className="flex h-full items-center justify-center text-sm text-muted-foreground">
        No collaboration network data available.
      </div>
    );
  }

  return (
    <ReactEChartsCore
      ref={chartRef}
      echarts={echarts}
      option={option}
      style={{ width: "100%", height: "100%" }}
      onEvents={{ click: handleClick }}
      notMerge
    />
  );
}
