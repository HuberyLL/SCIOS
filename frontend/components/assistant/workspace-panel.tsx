"use client";

import { useCallback, useState } from "react";
import { Prism as SyntaxHighlighter } from "react-syntax-highlighter";
import { oneDark } from "react-syntax-highlighter/dist/esm/styles/prism";
import { Button } from "@/components/ui/button";
import { ScrollArea } from "@/components/ui/scroll-area";
import {
  X,
  ZoomIn,
  ZoomOut,
  Maximize2,
  FileText,
  Image as ImageIcon,
  Code2,
} from "lucide-react";
import type { Artifact } from "@/types";
import { EmptyWorkspace } from "./empty-workspace";
import { cn } from "@/lib/utils";

interface WorkspacePanelProps {
  artifact: Artifact | null;
  onClose: () => void;
}

const EXT_TO_LANG: Record<string, string> = {
  py: "python",
  ts: "typescript",
  tsx: "tsx",
  js: "javascript",
  jsx: "jsx",
  sh: "bash",
  r: "r",
  tex: "latex",
  csv: "csv",
};

function getLanguage(path: string): string {
  const ext = path.split(".").pop()?.toLowerCase() || "";
  return EXT_TO_LANG[ext] || "text";
}

const TYPE_ICONS: Record<string, React.ElementType> = {
  pdf: FileText,
  image: ImageIcon,
  code: Code2,
  text: FileText,
};

export function WorkspacePanel({ artifact, onClose }: WorkspacePanelProps) {
  const [zoom, setZoom] = useState(1);

  const handleZoomIn = useCallback(
    () => setZoom((z) => Math.min(z + 0.25, 3)),
    [],
  );
  const handleZoomOut = useCallback(
    () => setZoom((z) => Math.max(z - 0.25, 0.25)),
    [],
  );
  const handleFit = useCallback(() => setZoom(1), []);

  if (!artifact) {
    return (
      <div className="flex h-full flex-col border-l border-border/40 bg-background">
        <EmptyWorkspace />
      </div>
    );
  }

  const Icon = TYPE_ICONS[artifact.type] || FileText;

  return (
    <div className="flex h-full flex-col border-l border-border/40 bg-background">
      <div className="flex items-center gap-2 border-b border-border/40 px-3 py-2">
        <Icon className="h-3.5 w-3.5 text-muted-foreground" />
        <span className="flex-1 truncate text-xs font-medium">
          {artifact.label}
        </span>
        {artifact.type === "image" && (
          <div className="flex items-center gap-0.5">
            <Button
              variant="ghost"
              size="icon"
              className="h-6 w-6"
              onClick={handleZoomOut}
            >
              <ZoomOut className="h-3 w-3" />
            </Button>
            <span className="min-w-[3ch] text-center text-[10px] text-muted-foreground">
              {Math.round(zoom * 100)}%
            </span>
            <Button
              variant="ghost"
              size="icon"
              className="h-6 w-6"
              onClick={handleZoomIn}
            >
              <ZoomIn className="h-3 w-3" />
            </Button>
            <Button
              variant="ghost"
              size="icon"
              className="h-6 w-6"
              onClick={handleFit}
            >
              <Maximize2 className="h-3 w-3" />
            </Button>
          </div>
        )}
        <Button
          variant="ghost"
          size="icon"
          className="h-6 w-6"
          onClick={onClose}
        >
          <X className="h-3 w-3" />
        </Button>
      </div>

      <div className="flex-1 overflow-hidden">
        {artifact.type === "pdf" && (
          <iframe
            src={`/api/v1/assistant/workspace/${artifact.path}`}
            className="h-full w-full border-0"
            title={artifact.label}
          />
        )}

        {artifact.type === "image" && (
          <ScrollArea className="h-full">
            <div className="flex items-center justify-center p-4">
              <img
                src={`/api/v1/assistant/workspace/${artifact.path}`}
                alt={artifact.label}
                className={cn("max-w-full rounded-md transition-transform")}
                style={{ transform: `scale(${zoom})`, transformOrigin: "top center" }}
              />
            </div>
          </ScrollArea>
        )}

        {(artifact.type === "code" || artifact.type === "text") && (
          <ScrollArea className="h-full">
            <div className="p-1">
              <SyntaxHighlighter
                language={getLanguage(artifact.path)}
                style={oneDark}
                showLineNumbers
                customStyle={{
                  margin: 0,
                  borderRadius: "0.375rem",
                  fontSize: "0.75rem",
                }}
              >
                {`// Loading ${artifact.path} ...`}
              </SyntaxHighlighter>
            </div>
          </ScrollArea>
        )}
      </div>
    </div>
  );
}
