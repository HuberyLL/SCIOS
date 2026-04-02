"use client";

import { ExternalLink, FileText, BookOpen, X, Users, Calendar, Hash } from "lucide-react";
import { Dialog, DialogContent, DialogHeader, DialogTitle } from "@/components/ui/dialog";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { ScrollArea } from "@/components/ui/scroll-area";
import { Separator } from "@/components/ui/separator";
import type { PaperResult } from "@/types";

interface PaperDetailPanelProps {
  paper: PaperResult | null;
  open: boolean;
  onClose: () => void;
}

export function PaperDetailPanel({ paper, open, onClose }: PaperDetailPanelProps) {
  if (!paper) return null;

  return (
    <Dialog open={open} onOpenChange={(v) => !v && onClose()}>
      <DialogContent
        showCloseButton={false}
        className="fixed top-0 right-0 left-auto h-full w-full max-w-md translate-x-0 translate-y-0 rounded-none rounded-l-xl border-l sm:max-w-md data-open:animate-in data-open:slide-in-from-right data-closed:animate-out data-closed:slide-out-to-right data-open:fade-in-0 data-closed:fade-out-0 data-open:zoom-in-100 data-closed:zoom-out-100"
      >
        <DialogHeader className="flex-row items-start justify-between gap-2">
          <DialogTitle className="pr-8 text-base font-semibold leading-snug">
            {paper.title}
          </DialogTitle>
          <Button variant="ghost" size="icon-sm" onClick={onClose} className="shrink-0">
            <X className="h-4 w-4" />
          </Button>
        </DialogHeader>

        <ScrollArea className="flex-1 -mx-4 px-4">
          <div className="space-y-5 pb-6">
            {/* Authors */}
            {paper.authors.length > 0 && (
              <div className="space-y-1.5">
                <div className="flex items-center gap-1.5 text-xs font-medium text-muted-foreground">
                  <Users className="h-3.5 w-3.5" />
                  Authors
                </div>
                <p className="text-sm leading-relaxed">{paper.authors.join(", ")}</p>
              </div>
            )}

            {/* Meta row */}
            <div className="flex flex-wrap gap-2">
              {paper.published_date && (
                <Badge variant="outline" className="gap-1 font-normal">
                  <Calendar className="h-3 w-3" />
                  {paper.published_date}
                </Badge>
              )}
              {paper.citation_count > 0 && (
                <Badge variant="outline" className="gap-1 font-normal">
                  <Hash className="h-3 w-3" />
                  {paper.citation_count} citations
                </Badge>
              )}
              {paper.source && (
                <Badge variant="secondary" className="font-normal">
                  {paper.source}
                </Badge>
              )}
              {paper.categories.map((cat) => (
                <Badge key={cat} variant="secondary" className="font-normal">
                  {cat}
                </Badge>
              ))}
            </div>

            <Separator />

            {/* Abstract */}
            {paper.abstract && (
              <div className="space-y-1.5">
                <div className="flex items-center gap-1.5 text-xs font-medium text-muted-foreground">
                  <BookOpen className="h-3.5 w-3.5" />
                  Abstract
                </div>
                <p className="text-sm leading-relaxed text-foreground/90">
                  {paper.abstract}
                </p>
              </div>
            )}

            <Separator />

            {/* External links */}
            <div className="flex flex-wrap gap-2">
              {paper.pdf_url && (
                <Button variant="outline" size="sm" asChild className="gap-1.5">
                  <a href={paper.pdf_url} target="_blank" rel="noopener noreferrer">
                    <FileText className="h-3.5 w-3.5" />
                    PDF
                  </a>
                </Button>
              )}
              {paper.url && (
                <Button variant="outline" size="sm" asChild className="gap-1.5">
                  <a href={paper.url} target="_blank" rel="noopener noreferrer">
                    <ExternalLink className="h-3.5 w-3.5" />
                    Source
                  </a>
                </Button>
              )}
              {paper.doi && (
                <Button variant="outline" size="sm" asChild className="gap-1.5">
                  <a
                    href={`https://doi.org/${paper.doi}`}
                    target="_blank"
                    rel="noopener noreferrer"
                  >
                    <ExternalLink className="h-3.5 w-3.5" />
                    DOI
                  </a>
                </Button>
              )}
            </div>
          </div>
        </ScrollArea>
      </DialogContent>
    </Dialog>
  );
}
