"use client";

import { useMemo, useCallback, useRef } from "react";
import ReactEChartsCore from "echarts-for-react/lib/core";
import * as echarts from "echarts/core";
import { GraphChart } from "echarts/charts";
import { TooltipComponent, LegendComponent } from "echarts/components";
import { CanvasRenderer } from "echarts/renderers";
import type { CollaborationNetwork } from "@/types";

echarts.use([GraphChart, TooltipComponent, LegendComponent, CanvasRenderer]);

interface CollaborationGraphProps {
  data: CollaborationNetwork;
  onScholarClick: (paperIds: string[]) => void;
}

function clamp(value: number, min: number, max: number) {
  return Math.min(Math.max(value, min), max);
}

export function CollaborationGraph({ data, onScholarClick }: CollaborationGraphProps) {
  const chartRef = useRef<ReactEChartsCore>(null);

  const option = useMemo(() => {
    if (data.nodes.length === 0) return null;

    const maxCitations = Math.max(...data.nodes.map((n) => n.citation_count), 1);
    const maxWeight = Math.max(...data.edges.map((e) => e.weight), 1);

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
            `Papers: ${n.paper_count}`,
            `Citations: ${n.citation_count}`,
            n.is_new ? '<span style="color:#22c55e">● New Scholar</span>' : "",
          ]
            .filter(Boolean)
            .join("<br/>");
        },
      },
      _topPaperIds: n.top_paper_ids,
    }));

    const links = data.edges.map((e) => ({
      source: e.source,
      target: e.target,
      value: e.weight,
      lineStyle: {
        width: clamp((e.weight / maxWeight) * 5, 0.5, 6),
        opacity: 0.4,
      },
    }));

    return {
      tooltip: { show: true, enterable: true },
      legend: {
        data: ["Existing", "New"],
        bottom: 10,
        textStyle: { fontSize: 11 },
      },
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
  }, [data]);

  const handleClick = useCallback(
    (params: { data?: { _topPaperIds?: string[] } }) => {
      const paperIds = params.data?._topPaperIds;
      if (paperIds && paperIds.length > 0) {
        onScholarClick(paperIds);
      }
    },
    [onScholarClick],
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
