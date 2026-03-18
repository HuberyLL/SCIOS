"use client";

import { useEffect, useState } from "react";
import { motion, AnimatePresence } from "framer-motion";
import { Calendar, ExternalLink, FileText, Loader2 } from "lucide-react";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import { ScrollArea } from "@/components/ui/scroll-area";
import { Separator } from "@/components/ui/separator";
import { listBriefs } from "@/lib/api";
import type { BriefData, DailyBrief } from "@/types";

interface BriefDetailProps {
  taskId: string | null;
  taskTopic?: string;
  refreshSignal?: number;
}

function formatLocalDateTime(iso: string): string {
  const normalized = /([zZ]|[+-]\d{2}:\d{2})$/.test(iso) ? iso : `${iso}Z`;
  return new Date(normalized).toLocaleString(undefined, {
    year: "numeric",
    month: "long",
    day: "numeric",
    hour: "2-digit",
    minute: "2-digit",
    hour12: false,
    timeZone: Intl.DateTimeFormat().resolvedOptions().timeZone,
  });
}

function BriefCard({ brief, index }: { brief: BriefData; index: number }) {
  const content = brief.brief_content as DailyBrief;
  const [sourcesOpen, setSourcesOpen] = useState(false);

  return (
    <motion.div
      initial={{ opacity: 0, y: 12 }}
      animate={{ opacity: 1, y: 0 }}
      transition={{ delay: index * 0.06 }}
    >
      <Card className="border border-border/40 ring-0">
        <CardHeader className="pb-3">
          <div className="flex items-center justify-between">
            <div className="flex items-center gap-2">
              <Calendar className="h-3.5 w-3.5 text-muted-foreground" />
              <CardTitle className="text-sm font-medium">
                {formatLocalDateTime(brief.created_at)}
              </CardTitle>
            </div>
            <span className="text-[11px] text-muted-foreground">
              since {content.since_date}
            </span>
          </div>
        </CardHeader>

        <CardContent className="space-y-4">
          {content.new_hot_papers.length > 0 && (
            <div>
              <p className="mb-2 text-xs font-semibold uppercase tracking-wider text-foreground/60">
                Hot Papers
              </p>
              <div className="space-y-2">
                {content.new_hot_papers.map((paper, i) => (
                  <div key={i} className="flex items-start justify-between gap-3">
                    <div className="min-w-0 flex-1">
                      <div className="flex items-center gap-1.5">
                        <span className="text-sm font-medium leading-snug">
                          {paper.title}
                        </span>
                        {paper.url && (
                          <a
                            href={paper.url}
                            target="_blank"
                            rel="noopener noreferrer"
                            className="shrink-0 text-muted-foreground hover:text-foreground"
                          >
                            <ExternalLink className="h-3 w-3" />
                          </a>
                        )}
                      </div>
                      {paper.relevance_reason && (
                        <p className="mt-0.5 text-xs leading-relaxed text-muted-foreground">
                          {paper.relevance_reason}
                        </p>
                      )}
                    </div>
                    {paper.citation_count > 0 && (
                      <Badge
                        variant="secondary"
                        className="shrink-0 font-mono text-[10px]"
                      >
                        {paper.citation_count}
                      </Badge>
                    )}
                  </div>
                ))}
              </div>
            </div>
          )}

          {content.trend_summary && (
            <div>
              <Separator className="mb-3" />
              <p className="mb-1 text-xs font-semibold uppercase tracking-wider text-foreground/60">
                Trend Summary
              </p>
              <p className="text-sm leading-relaxed text-muted-foreground">
                {content.trend_summary}
              </p>
            </div>
          )}

          {content.sources.length > 0 && (
            <div>
              <button
                onClick={() => setSourcesOpen(!sourcesOpen)}
                className="text-[11px] text-muted-foreground/60 underline-offset-2 hover:underline"
              >
                {sourcesOpen ? "Hide" : "Show"} sources ({content.sources.length})
              </button>
              {sourcesOpen && (
                <ul className="mt-1.5 space-y-0.5">
                  {content.sources.map((url, i) => (
                    <li key={i}>
                      <a
                        href={url}
                        target="_blank"
                        rel="noopener noreferrer"
                        className="break-all text-[11px] text-muted-foreground hover:underline"
                      >
                        {url}
                      </a>
                    </li>
                  ))}
                </ul>
              )}
            </div>
          )}
        </CardContent>
      </Card>
    </motion.div>
  );
}

export function BriefDetail({ taskId, taskTopic, refreshSignal = 0 }: BriefDetailProps) {
  const [briefs, setBriefs] = useState<BriefData[]>([]);
  const [loading, setLoading] = useState(false);

  useEffect(() => {
    if (!taskId) {
      return;
    }
    let cancelled = false;
    Promise.resolve().then(async () => {
      if (cancelled) return;
      setLoading(true);
      try {
        const data = await listBriefs(taskId);
        if (!cancelled) setBriefs(data);
      } catch {
        if (!cancelled) setBriefs([]);
      } finally {
        if (!cancelled) setLoading(false);
      }
    });

    return () => {
      cancelled = true;
    };
  }, [taskId, refreshSignal]);

  useEffect(() => {
    if (!taskId) return;

    let cancelled = false;
    const timer = setInterval(() => {
      Promise.resolve().then(async () => {
        try {
          const data = await listBriefs(taskId);
          if (!cancelled) setBriefs(data);
        } catch {
          // Keep previous data when fallback polling fails once.
        }
      });
    }, 12000);

    return () => {
      cancelled = true;
      clearInterval(timer);
    };
  }, [taskId]);

  if (!taskId) {
    return (
      <div className="flex h-full items-center justify-center">
        <div className="text-center">
          <FileText className="mx-auto mb-2 h-8 w-8 text-muted-foreground/30" />
          <p className="text-sm text-muted-foreground">
            Select a subscription to view briefs
          </p>
        </div>
      </div>
    );
  }

  if (loading) {
    return (
      <div className="flex h-40 items-center justify-center">
        <Loader2 className="h-5 w-5 animate-spin text-muted-foreground" />
      </div>
    );
  }

  if (briefs.length === 0) {
    return (
      <div className="flex h-40 items-center justify-center">
        <p className="text-xs text-muted-foreground">
          No briefs generated yet for this topic.
        </p>
      </div>
    );
  }

  return (
    <ScrollArea className="h-[calc(100vh-12rem)]">
      <div className="space-y-4 pr-2 pb-1 pl-1">
        {taskTopic && (
          <h2 className="text-lg font-semibold tracking-tight">{taskTopic}</h2>
        )}
        <AnimatePresence>
          {briefs.map((brief, i) => (
            <BriefCard key={brief.id} brief={brief} index={i} />
          ))}
        </AnimatePresence>
      </div>
    </ScrollArea>
  );
}
