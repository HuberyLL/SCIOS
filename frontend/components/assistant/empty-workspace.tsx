"use client";

import { FileOutput } from "lucide-react";

export function EmptyWorkspace() {
  return (
    <div className="flex h-full flex-col items-center justify-center gap-4 px-8">
      <div className="relative">
        <div className="absolute inset-0 rounded-full bg-primary/5 blur-2xl" />
        <div className="relative flex h-20 w-20 items-center justify-center rounded-2xl border border-border/50 bg-muted/30">
          <FileOutput className="h-8 w-8 text-muted-foreground/30" />
        </div>
      </div>
      <div className="text-center space-y-1.5">
        <p className="font-mono text-xs font-medium tracking-wider text-foreground/20 uppercase">
          Workspace
        </p>
        <p className="max-w-[200px] text-xs leading-relaxed text-muted-foreground/50">
          Your generated documents and charts will appear here.
        </p>
      </div>
    </div>
  );
}
