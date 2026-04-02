"use client";

import { AlertTriangle, Lightbulb, FileText } from "lucide-react";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import type { ResearchGaps, GapImpact } from "@/types";

interface ResearchGapsViewProps {
  data: ResearchGaps;
  onPaperClick: (paperId: string) => void;
}

const IMPACT_VARIANT: Record<GapImpact, "destructive" | "secondary" | "outline"> = {
  high: "destructive",
  medium: "secondary",
  low: "outline",
};

const IMPACT_LABEL: Record<GapImpact, string> = {
  high: "High Impact",
  medium: "Medium Impact",
  low: "Low Impact",
};

export function ResearchGapsView({ data, onPaperClick }: ResearchGapsViewProps) {
  if (data.gaps.length === 0) {
    return (
      <div className="flex h-full items-center justify-center text-sm text-muted-foreground">
        No research gaps identified.
      </div>
    );
  }

  return (
    <div className="space-y-6 overflow-auto p-1">
      <div className="grid gap-4 md:grid-cols-2">
        {data.gaps.map((gap) => (
          <Card key={gap.gap_id} className="transition-shadow hover:shadow-md">
            <CardHeader className="pb-3">
              <div className="flex items-start justify-between gap-2">
                <CardTitle className="text-sm font-semibold leading-snug">
                  <AlertTriangle className="mr-1.5 inline-block h-3.5 w-3.5 text-amber-500" />
                  {gap.title}
                </CardTitle>
                <Badge variant={IMPACT_VARIANT[gap.impact]} className="shrink-0 text-[10px]">
                  {IMPACT_LABEL[gap.impact]}
                </Badge>
              </div>
            </CardHeader>
            <CardContent className="space-y-3">
              <p className="text-xs leading-relaxed text-muted-foreground">
                {gap.description}
              </p>

              {gap.potential_approaches.length > 0 && (
                <div className="space-y-1.5">
                  <div className="flex items-center gap-1 text-[11px] font-medium text-foreground/70">
                    <Lightbulb className="h-3 w-3" />
                    Potential Approaches
                  </div>
                  <ul className="space-y-0.5">
                    {gap.potential_approaches.map((approach, i) => (
                      <li
                        key={i}
                        className="pl-3 text-[11px] leading-snug text-muted-foreground before:absolute before:left-0 before:content-['•'] relative"
                      >
                        {approach}
                      </li>
                    ))}
                  </ul>
                </div>
              )}

              {gap.evidence_paper_ids.length > 0 && (
                <div className="flex flex-wrap gap-1">
                  {gap.evidence_paper_ids.map((pid) => (
                    <button
                      key={pid}
                      onClick={() => onPaperClick(pid)}
                      className="inline-flex items-center gap-0.5 rounded-md border px-1.5 py-0.5 text-[10px] text-muted-foreground transition-colors hover:bg-muted hover:text-foreground"
                    >
                      <FileText className="h-2.5 w-2.5" />
                      {pid.length > 12 ? `${pid.slice(0, 12)}…` : pid}
                    </button>
                  ))}
                </div>
              )}
            </CardContent>
          </Card>
        ))}
      </div>

      {data.summary && (
        <div className="rounded-lg border bg-muted/30 p-4">
          <p className="text-xs font-medium text-foreground/70 mb-1.5">Summary</p>
          <p className="text-sm leading-relaxed text-foreground/90">{data.summary}</p>
        </div>
      )}
    </div>
  );
}
