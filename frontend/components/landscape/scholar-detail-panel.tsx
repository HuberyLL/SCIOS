"use client";

import {
  ExternalLink,
  X,
  Building2,
  FileText,
  Hash,
  Award,
  Sparkles,
  ChevronRight,
} from "lucide-react";
import { Dialog, DialogContent, DialogHeader, DialogTitle } from "@/components/ui/dialog";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { ScrollArea } from "@/components/ui/scroll-area";
import { Separator } from "@/components/ui/separator";
import type { PaperResult, ScholarNode } from "@/types";

interface ScholarDetailPanelProps {
  scholar: ScholarNode | null;
  paperMap: Map<string, PaperResult>;
  open: boolean;
  onClose: () => void;
  onPaperClick: (paperId: string) => void;
}

export function ScholarDetailPanel({
  scholar,
  paperMap,
  open,
  onClose,
  onPaperClick,
}: ScholarDetailPanelProps) {
  if (!scholar) return null;

  const hasS2Profile = !scholar.scholar_id.startsWith("name:");
  const s2Url = hasS2Profile
    ? `https://www.semanticscholar.org/author/${scholar.scholar_id}`
    : null;

  const topPapers = scholar.top_paper_ids
    .map((pid) => paperMap.get(pid))
    .filter((p): p is PaperResult => p != null);

  return (
    <Dialog open={open} onOpenChange={(v) => !v && onClose()}>
      <DialogContent
        showCloseButton={false}
        className="fixed top-0 right-0 left-auto h-full w-full max-w-md translate-x-0 translate-y-0 rounded-none rounded-l-xl border-l sm:max-w-md data-open:animate-in data-open:slide-in-from-right data-closed:animate-out data-closed:slide-out-to-right data-open:fade-in-0 data-closed:fade-out-0 data-open:zoom-in-100 data-closed:zoom-out-100"
      >
        <DialogHeader className="flex-row items-start justify-between gap-2">
          <div className="flex items-center gap-2 pr-8">
            <DialogTitle className="text-base font-semibold leading-snug">
              {scholar.name}
            </DialogTitle>
            {scholar.is_new && (
              <Badge className="gap-1 bg-emerald-500 text-white">
                <Sparkles className="h-3 w-3" />
                New
              </Badge>
            )}
          </div>
          <Button variant="ghost" size="icon-sm" onClick={onClose} className="shrink-0">
            <X className="h-4 w-4" />
          </Button>
        </DialogHeader>

        <ScrollArea className="flex-1 -mx-4 px-4">
          <div className="space-y-5 pb-6">
            {/* Metrics */}
            <div className="flex flex-wrap gap-2">
              {scholar.h_index > 0 && (
                <Badge variant="outline" className="gap-1 font-normal">
                  <Award className="h-3 w-3" />
                  h-index: {scholar.h_index}
                </Badge>
              )}
              <Badge variant="outline" className="gap-1 font-normal">
                <FileText className="h-3 w-3" />
                {scholar.paper_count} papers
              </Badge>
              <Badge variant="outline" className="gap-1 font-normal">
                <Hash className="h-3 w-3" />
                {scholar.citation_count.toLocaleString()} citations
              </Badge>
            </div>

            {/* Affiliations */}
            {scholar.affiliations.length > 0 && (
              <>
                <Separator />
                <div className="space-y-1.5">
                  <div className="flex items-center gap-1.5 text-xs font-medium text-muted-foreground">
                    <Building2 className="h-3.5 w-3.5" />
                    Affiliations
                  </div>
                  <ul className="space-y-1">
                    {scholar.affiliations.map((aff) => (
                      <li key={aff} className="text-sm leading-relaxed text-foreground/90">
                        {aff}
                      </li>
                    ))}
                  </ul>
                </div>
              </>
            )}

            {/* Top papers */}
            {topPapers.length > 0 && (
              <>
                <Separator />
                <div className="space-y-2">
                  <div className="flex items-center gap-1.5 text-xs font-medium text-muted-foreground">
                    <FileText className="h-3.5 w-3.5" />
                    Representative Papers
                  </div>
                  <ul className="space-y-1">
                    {topPapers.map((p) => (
                      <li key={p.paper_id}>
                        <button
                          type="button"
                          className="group flex w-full items-start gap-2 rounded-md px-2 py-1.5 text-left transition-colors hover:bg-muted/60"
                          onClick={() => {
                            onClose();
                            onPaperClick(p.paper_id);
                          }}
                        >
                          <span className="flex-1 text-sm leading-snug text-foreground/90 group-hover:text-foreground">
                            {p.title}
                          </span>
                          <ChevronRight className="mt-0.5 h-3.5 w-3.5 shrink-0 text-muted-foreground/40 group-hover:text-muted-foreground" />
                        </button>
                        <div className="flex gap-2 px-2 text-[11px] text-muted-foreground/60">
                          {p.published_date && <span>{p.published_date}</span>}
                          {p.citation_count > 0 && (
                            <span>{p.citation_count} citations</span>
                          )}
                        </div>
                      </li>
                    ))}
                  </ul>
                </div>
              </>
            )}

            <Separator />

            {/* External link */}
            {s2Url && (
              <div className="flex flex-wrap gap-2">
                <Button variant="outline" size="sm" asChild className="gap-1.5">
                  <a href={s2Url} target="_blank" rel="noopener noreferrer">
                    <ExternalLink className="h-3.5 w-3.5" />
                    Semantic Scholar Profile
                  </a>
                </Button>
              </div>
            )}
          </div>
        </ScrollArea>
      </DialogContent>
    </Dialog>
  );
}
