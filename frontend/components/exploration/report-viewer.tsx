"use client";

import React, { useState } from "react";
import { motion } from "framer-motion";
import {
  Lightbulb,
  GraduationCap,
  BookOpen,
  TrendingUp,
  ExternalLink,
  ChevronDown,
  ChevronRight,
  Search,
  Link2,
} from "lucide-react";
import {
  Card,
  CardContent,
  CardHeader,
  CardTitle,
} from "@/components/ui/card";
import { Avatar, AvatarFallback } from "@/components/ui/avatar";
import { Badge } from "@/components/ui/badge";
import { Separator } from "@/components/ui/separator";
import { Button } from "@/components/ui/button";
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table";
import type { ExplorationReport } from "@/types";

const fadeUp = {
  initial: { opacity: 0, y: 20 },
  animate: { opacity: 1, y: 0 },
};

function SectionHeading({
  icon: Icon,
  title,
}: {
  icon: React.ComponentType<{ className?: string }>;
  title: string;
}) {
  return (
    <div className="mb-6 flex items-center gap-2.5">
      <Icon className="h-5 w-5 text-foreground/70" />
      <h2 className="text-xl font-semibold tracking-tight">{title}</h2>
    </div>
  );
}

// ---------------------------------------------------------------------------
// Core Concepts
// ---------------------------------------------------------------------------

function CoreConceptsSection({ report }: { report: ExplorationReport }) {
  return (
    <motion.section {...fadeUp} transition={{ delay: 0.1 }}>
      <SectionHeading icon={Lightbulb} title="Core Concepts" />
      <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-3">
        {report.core_concepts.map((c, i) => (
          <motion.div
            key={i}
            initial={{ opacity: 0, y: 16 }}
            animate={{ opacity: 1, y: 0 }}
            transition={{ delay: 0.15 + i * 0.06 }}
          >
            <Card className="h-full border-border/40">
              <CardHeader className="pb-2">
                <CardTitle className="text-sm font-semibold">{c.term}</CardTitle>
              </CardHeader>
              <CardContent>
                <p className="text-sm leading-relaxed text-muted-foreground">
                  {c.explanation}
                </p>
              </CardContent>
            </Card>
          </motion.div>
        ))}
      </div>
    </motion.section>
  );
}

// ---------------------------------------------------------------------------
// Key Scholars
// ---------------------------------------------------------------------------

function KeyScholarsSection({ report }: { report: ExplorationReport }) {
  const [expanded, setExpanded] = useState<number | null>(null);

  return (
    <motion.section {...fadeUp} transition={{ delay: 0.2 }}>
      <SectionHeading icon={GraduationCap} title="Key Scholars" />
      <div className="space-y-3">
        {report.key_scholars.map((s, i) => {
          const initials = s.name
            .split(" ")
            .map((w) => w[0])
            .join("")
            .slice(0, 2)
            .toUpperCase();
          const isOpen = expanded === i;

          return (
            <motion.div
              key={i}
              initial={{ opacity: 0, y: 12 }}
              animate={{ opacity: 1, y: 0 }}
              transition={{ delay: 0.25 + i * 0.05 }}
            >
              <Card className="border-border/40">
                <button
                  onClick={() => setExpanded(isOpen ? null : i)}
                  className="flex w-full items-center gap-4 p-4 text-left"
                >
                  <Avatar className="h-9 w-9 shrink-0">
                    <AvatarFallback className="bg-muted text-xs font-medium">
                      {initials}
                    </AvatarFallback>
                  </Avatar>
                  <div className="min-w-0 flex-1">
                    <p className="truncate text-sm font-medium">{s.name}</p>
                    <p className="truncate text-xs text-muted-foreground">
                      {s.affiliation}
                    </p>
                  </div>
                  {isOpen ? (
                    <ChevronDown className="h-4 w-4 shrink-0 text-muted-foreground" />
                  ) : (
                    <ChevronRight className="h-4 w-4 shrink-0 text-muted-foreground" />
                  )}
                </button>

                {isOpen && (
                  <div className="border-t border-border/30 px-4 pb-4 pt-3">
                    <p className="mb-2 text-sm leading-relaxed text-muted-foreground">
                      {s.contribution_summary}
                    </p>
                    {s.representative_works.length > 0 && (
                      <>
                        <Separator className="my-2" />
                        <p className="mb-1 text-xs font-medium text-foreground/60">
                          Representative Works
                        </p>
                        <ul className="space-y-0.5">
                          {s.representative_works.map((w, j) => (
                            <li
                              key={j}
                              className="text-xs leading-relaxed text-muted-foreground"
                            >
                              &bull; {w}
                            </li>
                          ))}
                        </ul>
                      </>
                    )}
                  </div>
                )}
              </Card>
            </motion.div>
          );
        })}
      </div>
    </motion.section>
  );
}

// ---------------------------------------------------------------------------
// Must-Read Papers
// ---------------------------------------------------------------------------

function MustReadPapersSection({ report }: { report: ExplorationReport }) {
  const [openSummary, setOpenSummary] = useState<number | null>(null);

  return (
    <motion.section {...fadeUp} transition={{ delay: 0.3 }}>
      <SectionHeading icon={BookOpen} title="Must-Read Papers" />
      <Card className="overflow-hidden border-border/40">
        <Table>
          <TableHeader>
            <TableRow className="hover:bg-transparent">
              <TableHead className="w-[45%]">Title</TableHead>
              <TableHead>Authors</TableHead>
              <TableHead className="text-center">Year</TableHead>
              <TableHead className="text-right">Citations</TableHead>
            </TableRow>
          </TableHeader>
          <TableBody>
            {report.must_read_papers.map((p, i) => (
              <React.Fragment key={`paper-${i}`}>
                <TableRow
                  className="cursor-pointer"
                  onClick={() => setOpenSummary(openSummary === i ? null : i)}
                >
                  <TableCell className="max-w-xs">
                    <div className="flex items-start gap-1.5">
                      <span className="text-sm font-medium leading-snug">
                        {p.title}
                      </span>
                      {p.url && (
                        <a
                          href={p.url}
                          target="_blank"
                          rel="noopener noreferrer"
                          onClick={(e) => e.stopPropagation()}
                          className="mt-0.5 shrink-0 text-muted-foreground transition-colors hover:text-foreground"
                        >
                          <ExternalLink className="h-3.5 w-3.5" />
                        </a>
                      )}
                    </div>
                    {p.venue && (
                      <span className="text-xs text-muted-foreground">
                        {p.venue}
                      </span>
                    )}
                  </TableCell>
                  <TableCell className="text-xs text-muted-foreground">
                    {p.authors.slice(0, 3).join(", ")}
                    {p.authors.length > 3 && " et al."}
                  </TableCell>
                  <TableCell className="text-center text-xs">{p.year}</TableCell>
                  <TableCell className="text-right">
                    <Badge variant="secondary" className="font-mono text-[11px]">
                      {p.citation_count.toLocaleString()}
                    </Badge>
                  </TableCell>
                </TableRow>
                {openSummary === i && (
                  <TableRow key={`summary-${i}`}>
                    <TableCell
                      colSpan={4}
                      className="bg-muted/30 text-sm leading-relaxed text-muted-foreground"
                    >
                      {p.summary}
                    </TableCell>
                  </TableRow>
                )}
              </React.Fragment>
            ))}
          </TableBody>
        </Table>
      </Card>
    </motion.section>
  );
}

// ---------------------------------------------------------------------------
// Trends & Challenges
// ---------------------------------------------------------------------------

function TrendsSection({ report }: { report: ExplorationReport }) {
  const t = report.trends_and_challenges;
  return (
    <motion.section {...fadeUp} transition={{ delay: 0.4 }}>
      <SectionHeading icon={TrendingUp} title="Trends & Challenges" />
      <div className="space-y-6">
        <div>
          <h3 className="mb-2 text-sm font-semibold text-foreground/80">
            Recent Progress
          </h3>
          <p className="text-sm leading-relaxed text-muted-foreground">
            {t.recent_progress}
          </p>
        </div>

        <div className="grid gap-6 sm:grid-cols-2">
          <div>
            <h3 className="mb-2 text-sm font-semibold text-foreground/80">
              Emerging Trends
            </h3>
            <ul className="space-y-1.5">
              {t.emerging_trends.map((item, i) => (
                <li
                  key={i}
                  className="flex items-start gap-2 text-sm leading-relaxed text-muted-foreground"
                >
                  <TrendingUp className="mt-0.5 h-3.5 w-3.5 shrink-0 text-foreground/30" />
                  {item}
                </li>
              ))}
            </ul>
          </div>
          <div>
            <h3 className="mb-2 text-sm font-semibold text-foreground/80">
              Open Challenges
            </h3>
            <ul className="space-y-1.5">
              {t.open_challenges.map((item, i) => (
                <li
                  key={i}
                  className="flex items-start gap-2 text-sm leading-relaxed text-muted-foreground"
                >
                  <span className="mt-0.5 text-foreground/30">&bull;</span>
                  {item}
                </li>
              ))}
            </ul>
          </div>
        </div>

        <div>
          <h3 className="mb-2 text-sm font-semibold text-foreground/80">
            Future Directions
          </h3>
          <p className="text-sm leading-relaxed text-muted-foreground">
            {t.future_directions}
          </p>
        </div>
      </div>
    </motion.section>
  );
}

// ---------------------------------------------------------------------------
// Sources
// ---------------------------------------------------------------------------

function SourcesSection({ sources }: { sources: string[] }) {
  const [open, setOpen] = useState(false);
  if (sources.length === 0) return null;

  return (
    <motion.section {...fadeUp} transition={{ delay: 0.5 }}>
      <button
        onClick={() => setOpen(!open)}
        className="flex items-center gap-2 text-sm font-medium text-muted-foreground transition-colors hover:text-foreground"
      >
        <Link2 className="h-4 w-4" />
        Sources ({sources.length})
        {open ? (
          <ChevronDown className="h-3.5 w-3.5" />
        ) : (
          <ChevronRight className="h-3.5 w-3.5" />
        )}
      </button>
      {open && (
        <ul className="mt-3 space-y-1 pl-6">
          {sources.map((url, i) => (
            <li key={i}>
              <a
                href={url}
                target="_blank"
                rel="noopener noreferrer"
                className="break-all text-xs text-muted-foreground underline-offset-2 hover:underline"
              >
                {url}
              </a>
            </li>
          ))}
        </ul>
      )}
    </motion.section>
  );
}

// ---------------------------------------------------------------------------
// Main ReportViewer
// ---------------------------------------------------------------------------

interface ReportViewerProps {
  report: ExplorationReport;
  onNewSearch: () => void;
}

export function ReportViewer({ report, onNewSearch }: ReportViewerProps) {
  return (
    <div className="mx-auto max-w-4xl px-6 py-10">
      <motion.div
        initial={{ opacity: 0 }}
        animate={{ opacity: 1 }}
        className="mb-10 flex items-center justify-between"
      >
        <div>
          <p className="text-xs font-medium uppercase tracking-widest text-muted-foreground">
            Exploration Report
          </p>
          <h1 className="mt-1 text-2xl font-bold tracking-tight sm:text-3xl">
            {report.topic}
          </h1>
        </div>
        <Button variant="outline" size="sm" onClick={onNewSearch} className="gap-2">
          <Search className="h-3.5 w-3.5" />
          New Search
        </Button>
      </motion.div>

      <div className="space-y-12">
        <CoreConceptsSection report={report} />
        <KeyScholarsSection report={report} />
        <MustReadPapersSection report={report} />
        <TrendsSection report={report} />
        <SourcesSection sources={report.sources} />
      </div>
    </div>
  );
}
