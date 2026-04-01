"use client";

import { memo } from "react";
import { Handle, Position, type NodeProps } from "@xyflow/react";
import { Cpu, FileText, Flag } from "lucide-react";
import { Badge } from "@/components/ui/badge";
import type { TechTreeNodeType } from "@/types";

export interface TechNodeData {
  label: string;
  nodeType: TechTreeNodeType;
  year: number | null;
  description: string;
  paperIds: string[];
  isNew: boolean;
}

const TYPE_CONFIG: Record<
  TechTreeNodeType,
  { icon: typeof Cpu; bg: string; border: string; text: string }
> = {
  method: {
    icon: Cpu,
    bg: "bg-blue-50 dark:bg-blue-950/40",
    border: "border-blue-300 dark:border-blue-700",
    text: "text-blue-700 dark:text-blue-300",
  },
  paper: {
    icon: FileText,
    bg: "bg-amber-50 dark:bg-amber-950/40",
    border: "border-amber-300 dark:border-amber-700",
    text: "text-amber-700 dark:text-amber-300",
  },
  milestone: {
    icon: Flag,
    bg: "bg-emerald-50 dark:bg-emerald-950/40",
    border: "border-emerald-300 dark:border-emerald-700",
    text: "text-emerald-700 dark:text-emerald-300",
  },
};

function TechTreeNodeInner({ data }: NodeProps) {
  const d = data as unknown as TechNodeData;
  const cfg = TYPE_CONFIG[d.nodeType] || TYPE_CONFIG.method;
  const Icon = cfg.icon;

  return (
    <div
      className={`group relative rounded-lg border px-3 py-2 shadow-sm transition-shadow hover:shadow-md ${cfg.bg} ${cfg.border} min-w-[140px] max-w-[220px]`}
    >
      <Handle type="target" position={Position.Top} className="!bg-muted-foreground/40 !h-2 !w-2" />

      {d.isNew && (
        <Badge className="absolute -top-2.5 -right-2.5 animate-pulse bg-emerald-500 px-1.5 py-0 text-[10px] text-white">
          New!
        </Badge>
      )}

      <div className="flex items-start gap-2">
        <Icon className={`mt-0.5 h-3.5 w-3.5 shrink-0 ${cfg.text}`} />
        <div className="min-w-0 flex-1">
          <p className="truncate text-xs font-semibold leading-tight text-foreground">
            {d.label}
          </p>
          {d.year && (
            <p className="mt-0.5 text-[10px] text-muted-foreground">{d.year}</p>
          )}
        </div>
      </div>

      {d.description && (
        <p className="mt-1 line-clamp-2 text-[10px] leading-snug text-muted-foreground">
          {d.description}
        </p>
      )}

      <Handle type="source" position={Position.Bottom} className="!bg-muted-foreground/40 !h-2 !w-2" />
    </div>
  );
}

export const TechTreeNode = memo(TechTreeNodeInner);
