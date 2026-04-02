"use client";

import { memo, useState } from "react";
import { Handle, Position, type NodeProps } from "@xyflow/react";
import {
  Landmark,
  Zap,
  Settings2,
  ArrowUpRight,
  BookOpen,
  HelpCircle,
} from "lucide-react";
import { Badge } from "@/components/ui/badge";
import type { TechTreeNodeType } from "@/types";

export interface TechNodeData {
  label: string;
  nodeType: TechTreeNodeType;
  year: number | null;
  description: string;
  importance: number;
  depth: number;
  paperIds: string[];
  isNew: boolean;
}

const TYPE_CONFIG: Record<
  TechTreeNodeType,
  { icon: typeof Landmark; bg: string; border: string; text: string; label: string }
> = {
  foundation: {
    icon: Landmark,
    bg: "bg-violet-50 dark:bg-violet-950/40",
    border: "border-violet-400 dark:border-violet-600",
    text: "text-violet-700 dark:text-violet-300",
    label: "Foundation",
  },
  breakthrough: {
    icon: Zap,
    bg: "bg-emerald-50 dark:bg-emerald-950/40",
    border: "border-emerald-400 dark:border-emerald-600",
    text: "text-emerald-700 dark:text-emerald-300",
    label: "Breakthrough",
  },
  incremental: {
    icon: Settings2,
    bg: "bg-sky-50 dark:bg-sky-950/40",
    border: "border-sky-300 dark:border-sky-700",
    text: "text-sky-700 dark:text-sky-300",
    label: "Incremental",
  },
  application: {
    icon: ArrowUpRight,
    bg: "bg-amber-50 dark:bg-amber-950/40",
    border: "border-amber-400 dark:border-amber-600",
    text: "text-amber-700 dark:text-amber-300",
    label: "Application",
  },
  survey: {
    icon: BookOpen,
    bg: "bg-slate-100 dark:bg-slate-800/40",
    border: "border-slate-300 dark:border-slate-600",
    text: "text-slate-600 dark:text-slate-400",
    label: "Survey",
  },
  unverified: {
    icon: HelpCircle,
    bg: "bg-gray-50 dark:bg-gray-900/40",
    border: "border-dashed border-gray-300 dark:border-gray-600",
    text: "text-gray-500 dark:text-gray-400",
    label: "Unverified",
  },
};

function importanceToWidth(importance: number): number {
  return Math.round(130 + importance * 120);
}

function TechTreeNodeInner({ data }: NodeProps) {
  const d = data as unknown as TechNodeData;
  const cfg = TYPE_CONFIG[d.nodeType] || TYPE_CONFIG.incremental;
  const Icon = cfg.icon;
  const [hovered, setHovered] = useState(false);

  const importance = typeof d.importance === "number" ? d.importance : 0.5;
  const width = importanceToWidth(importance);
  const borderWeight = importance >= 0.7 ? "border-2" : "border";

  return (
    <div
      className={`group relative rounded-lg ${borderWeight} px-3 py-2 shadow-sm transition-all hover:shadow-md ${cfg.bg} ${cfg.border}`}
      style={{ width, minWidth: 130, maxWidth: 260 }}
      onMouseEnter={() => setHovered(true)}
      onMouseLeave={() => setHovered(false)}
    >
      <Handle
        type="target"
        position={Position.Top}
        className="opacity-0! h-1! w-1!"
      />

      {d.isNew && (
        <Badge className="absolute -top-2.5 -right-2.5 animate-pulse bg-emerald-500 px-1.5 py-0 text-[10px] text-white">
          New!
        </Badge>
      )}

      <div className="flex items-center gap-1.5">
        <Icon className={`h-3.5 w-3.5 shrink-0 ${cfg.text}`} />
        <p className="truncate text-xs font-semibold leading-tight text-foreground">
          {d.label}
        </p>
      </div>

      <div className="mt-0.5 flex items-center gap-1.5">
        {d.year && (
          <span className="text-[10px] text-muted-foreground">{d.year}</span>
        )}
        <span className={`text-[9px] ${cfg.text} opacity-70`}>
          {cfg.label}
        </span>
      </div>

      {hovered && d.description && (
        <div className="absolute left-1/2 top-full z-50 mt-2 w-64 -translate-x-1/2 rounded-md border bg-popover px-3 py-2 text-[11px] leading-relaxed text-popover-foreground shadow-lg">
          {d.description}
          {d.paperIds.length > 0 && (
            <p className="mt-1 text-[10px] text-muted-foreground">
              {d.paperIds.length} paper{d.paperIds.length > 1 ? "s" : ""}
            </p>
          )}
        </div>
      )}

      <Handle
        type="source"
        position={Position.Bottom}
        className="opacity-0! h-1! w-1!"
      />
    </div>
  );
}

export const TechTreeNode = memo(TechTreeNodeInner);

export { TYPE_CONFIG, importanceToWidth };
