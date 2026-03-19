"use client";

import { useEffect, useState } from "react";
import {
  Collapsible,
  CollapsibleContent,
  CollapsibleTrigger,
} from "@/components/ui/collapsible";
import { Badge } from "@/components/ui/badge";
import { ScrollArea } from "@/components/ui/scroll-area";
import {
  Loader2,
  CheckCircle2,
  XCircle,
  ChevronRight,
  Terminal,
  FileSearch,
  Code2,
  Globe,
  BookOpen,
  FileText,
  FlaskConical,
  Clock,
} from "lucide-react";
import type { ToolCallBlock } from "@/types";
import { cn } from "@/lib/utils";

const TOOL_ICONS: Record<string, React.ElementType> = {
  run_bash_command: Terminal,
  run_python_code: Code2,
  read_file: FileSearch,
  write_file: FileText,
  edit_file: FileText,
  glob_search: FileSearch,
  search_academic_papers: BookOpen,
  web_search: Globe,
  compile_latex: FileText,
  parse_csv_log: FlaskConical,
  get_system_time: Clock,
};

const TERMINAL_TOOLS = new Set(["run_bash_command", "run_python_code"]);

interface ToolCallCardProps {
  toolCall: ToolCallBlock;
}

export function ToolCallCard({ toolCall }: ToolCallCardProps) {
  const { tool_name, args, result, status } = toolCall;
  const [open, setOpen] = useState(false);

  useEffect(() => {
    if (status === "completed" || status === "error") {
      setOpen(true);
    }
  }, [status]);

  const Icon = TOOL_ICONS[tool_name] || Terminal;
  const isTerminal = TERMINAL_TOOLS.has(tool_name);

  const statusIcon =
    status === "running" ? (
      <Loader2 className="h-3.5 w-3.5 animate-spin text-blue-500" />
    ) : status === "completed" ? (
      <CheckCircle2 className="h-3.5 w-3.5 text-emerald-500" />
    ) : (
      <XCircle className="h-3.5 w-3.5 text-destructive" />
    );

  const displayName = tool_name.replace(/_/g, " ");
  const argsPreview =
    tool_name === "run_bash_command"
      ? (args.command as string) || ""
      : tool_name === "run_python_code"
        ? "python code"
        : Object.values(args).join(", ").slice(0, 60);

  return (
    <Collapsible open={open} onOpenChange={setOpen}>
      <CollapsibleTrigger asChild>
        <button
          className={cn(
            "flex w-full items-center gap-2 rounded-lg border px-3 py-2 text-left transition-colors",
            "hover:bg-muted/50",
            status === "running" && "border-blue-500/30 bg-blue-500/5",
            status === "completed" && "border-border bg-muted/30",
            status === "error" && "border-destructive/30 bg-destructive/5",
          )}
        >
          <ChevronRight
            className={cn(
              "h-3.5 w-3.5 shrink-0 text-muted-foreground transition-transform",
              open && "rotate-90",
            )}
          />
          <Icon className="h-3.5 w-3.5 shrink-0 text-muted-foreground" />
          <Badge variant="secondary" className="text-[10px] font-mono">
            {displayName}
          </Badge>
          {argsPreview && (
            <span className="truncate text-xs text-muted-foreground/70 font-mono">
              {argsPreview}
            </span>
          )}
          <span className="ml-auto shrink-0">{statusIcon}</span>
        </button>
      </CollapsibleTrigger>

      <CollapsibleContent>
        <div className="mt-1 space-y-2 rounded-lg border border-border/50 bg-muted/20 p-3">
          {Object.keys(args).length > 0 && (
            <div>
              <div className="mb-1 text-[10px] font-medium uppercase tracking-wider text-muted-foreground">
                Arguments
              </div>
              <pre className="overflow-x-auto rounded-md bg-zinc-950 p-2.5 font-mono text-xs text-zinc-300">
                {JSON.stringify(args, null, 2)}
              </pre>
            </div>
          )}

          {result !== undefined && (
            <div>
              <div className="mb-1 text-[10px] font-medium uppercase tracking-wider text-muted-foreground">
                Result
              </div>
              {isTerminal ? (
                <ScrollArea className="max-h-64">
                  <pre className="terminal-output">{result}</pre>
                </ScrollArea>
              ) : (
                <ScrollArea className="max-h-64">
                  <pre className="overflow-x-auto rounded-md bg-zinc-950 p-2.5 font-mono text-xs text-zinc-300 whitespace-pre-wrap wrap-break-word">
                    {result}
                  </pre>
                </ScrollArea>
              )}
            </div>
          )}

          {status === "running" && (
            <div className="flex items-center gap-2 text-xs text-muted-foreground">
              <Loader2 className="h-3 w-3 animate-spin" />
              Executing...
            </div>
          )}
        </div>
      </CollapsibleContent>
    </Collapsible>
  );
}
