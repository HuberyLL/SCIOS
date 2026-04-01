"use client";

import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table";
import { Badge } from "@/components/ui/badge";
import { Tooltip, TooltipContent, TooltipProvider, TooltipTrigger } from "@/components/ui/tooltip";
import type { ComparisonMatrix as ComparisonMatrixType, PaperComparison } from "@/types";

interface ComparisonMatrixProps {
  data: ComparisonMatrixType;
  onPaperClick: (paperId: string) => void;
}

function MethodologyCell({ paper }: { paper: PaperComparison }) {
  return (
    <TooltipProvider>
      <Tooltip>
        <TooltipTrigger asChild>
          <div className="space-y-0.5">
            <p className="text-xs font-medium">{paper.methodology.approach}</p>
            <p className="text-[11px] text-muted-foreground">{paper.methodology.key_technique}</p>
          </div>
        </TooltipTrigger>
        <TooltipContent side="top" className="max-w-xs">
          <p className="text-xs"><strong>Novelty:</strong> {paper.methodology.novelty}</p>
        </TooltipContent>
      </Tooltip>
    </TooltipProvider>
  );
}

function DatasetsCell({ paper }: { paper: PaperComparison }) {
  if (paper.datasets.length === 0) return <span className="text-xs text-muted-foreground">—</span>;
  return (
    <div className="flex flex-wrap gap-1">
      {paper.datasets.map((ds, i) => (
        <TooltipProvider key={i}>
          <Tooltip>
            <TooltipTrigger asChild>
              <Badge variant="outline" className="text-[10px] font-normal">
                {ds.name}
              </Badge>
            </TooltipTrigger>
            <TooltipContent side="top">
              <p className="text-xs">{ds.domain} · {ds.scale}</p>
            </TooltipContent>
          </Tooltip>
        </TooltipProvider>
      ))}
    </div>
  );
}

function MetricsCell({ paper }: { paper: PaperComparison }) {
  if (paper.metrics.length === 0) return <span className="text-xs text-muted-foreground">—</span>;
  return (
    <div className="space-y-0.5">
      {paper.metrics.slice(0, 3).map((m, i) => (
        <div key={i} className="flex items-baseline gap-1.5">
          <span className="text-xs font-medium tabular-nums">{m.value}</span>
          <span className="text-[10px] text-muted-foreground">
            {m.metric_name}
            {m.dataset && ` (${m.dataset})`}
          </span>
        </div>
      ))}
      {paper.metrics.length > 3 && (
        <p className="text-[10px] text-muted-foreground">
          +{paper.metrics.length - 3} more
        </p>
      )}
    </div>
  );
}

function LimitationsCell({ paper }: { paper: PaperComparison }) {
  if (paper.limitations.length === 0) return <span className="text-xs text-muted-foreground">—</span>;
  return (
    <ul className="list-inside list-disc space-y-0.5">
      {paper.limitations.slice(0, 2).map((lim, i) => (
        <li key={i} className="text-[11px] leading-snug text-muted-foreground">
          {lim}
        </li>
      ))}
      {paper.limitations.length > 2 && (
        <li className="text-[10px] text-muted-foreground/60">
          +{paper.limitations.length - 2} more
        </li>
      )}
    </ul>
  );
}

export function ComparisonMatrix({ data, onPaperClick }: ComparisonMatrixProps) {
  if (data.papers.length === 0) {
    return (
      <div className="flex h-full items-center justify-center text-sm text-muted-foreground">
        No comparison data available.
      </div>
    );
  }

  return (
    <div className="h-full overflow-auto rounded-lg border">
      <Table>
        <TableHeader className="sticky top-0 z-10 bg-background">
          <TableRow>
            <TableHead className="min-w-[200px] sticky left-0 z-20 bg-background">
              Paper
            </TableHead>
            <TableHead className="min-w-[60px]">Year</TableHead>
            <TableHead className="min-w-[180px]">Methodology</TableHead>
            <TableHead className="min-w-[160px]">Datasets</TableHead>
            <TableHead className="min-w-[180px]">Metrics</TableHead>
            <TableHead className="min-w-[200px]">Limitations</TableHead>
          </TableRow>
        </TableHeader>
        <TableBody>
          {data.papers.map((paper) => (
            <TableRow
              key={paper.paper_id}
              className="cursor-pointer transition-colors hover:bg-muted/50"
              onClick={() => onPaperClick(paper.paper_id)}
            >
              <TableCell className="sticky left-0 z-10 bg-background font-medium">
                <p className="line-clamp-2 text-xs leading-snug">{paper.title}</p>
              </TableCell>
              <TableCell className="text-xs tabular-nums text-muted-foreground">
                {paper.year ?? "—"}
              </TableCell>
              <TableCell>
                <MethodologyCell paper={paper} />
              </TableCell>
              <TableCell>
                <DatasetsCell paper={paper} />
              </TableCell>
              <TableCell>
                <MetricsCell paper={paper} />
              </TableCell>
              <TableCell>
                <LimitationsCell paper={paper} />
              </TableCell>
            </TableRow>
          ))}
        </TableBody>
      </Table>
    </div>
  );
}
