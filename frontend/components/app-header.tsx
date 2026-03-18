"use client";

import { Tabs, TabsList, TabsTrigger } from "@/components/ui/tabs";
import { Telescope, Radio } from "lucide-react";

interface AppHeaderProps {
  activeTab: string;
  onTabChange: (tab: string) => void;
}

export function AppHeader({ activeTab, onTabChange }: AppHeaderProps) {
  return (
    <header className="sticky top-0 z-50 w-full border-b border-border/40 bg-background/80 backdrop-blur-sm">
      <div className="mx-auto flex h-14 max-w-5xl items-center justify-between px-6">
        <span className="select-none font-mono text-sm font-semibold tracking-widest uppercase text-foreground/80">
          SCIOS
        </span>

        <Tabs value={activeTab} onValueChange={onTabChange}>
          <TabsList className="bg-muted/60">
            <TabsTrigger value="explore" className="gap-1.5 text-xs">
              <Telescope className="h-3.5 w-3.5" />
              Explore
            </TabsTrigger>
            <TabsTrigger value="monitor" className="gap-1.5 text-xs">
              <Radio className="h-3.5 w-3.5" />
              Monitor
            </TabsTrigger>
          </TabsList>
        </Tabs>

        <div className="w-14" />
      </div>
    </header>
  );
}
