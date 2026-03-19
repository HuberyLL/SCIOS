"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";
import { Telescope, Radio, BotMessageSquare } from "lucide-react";
import { cn } from "@/lib/utils";

interface AppHeaderProps {
  activeTab?: string;
  onTabChange?: (tab: string) => void;
}

export function AppHeader({ activeTab, onTabChange }: AppHeaderProps) {
  const pathname = usePathname();
  const isAssistant = pathname?.startsWith("/assistant");

  return (
    <header className="sticky top-0 z-50 w-full border-b border-border/40 bg-background/80 backdrop-blur-sm">
      <div className="mx-auto flex h-14 max-w-7xl items-center justify-between px-6">
        <Link
          href="/"
          className="select-none font-mono text-sm font-semibold tracking-widest uppercase text-foreground/80 hover:text-foreground transition-colors"
        >
          SCIOS
        </Link>

        <nav className="flex items-center gap-1 rounded-lg bg-muted/60 p-1">
          <button
            onClick={() => {
              if (isAssistant) {
                window.location.href = "/";
              }
              onTabChange?.("explore");
            }}
            className={cn(
              "inline-flex items-center gap-1.5 rounded-md px-3 py-1.5 text-xs font-medium transition-colors",
              !isAssistant && activeTab === "explore"
                ? "bg-background text-foreground shadow-sm"
                : "text-muted-foreground hover:text-foreground",
            )}
          >
            <Telescope className="h-3.5 w-3.5" />
            Explore
          </button>
          <button
            onClick={() => {
              if (isAssistant) {
                window.location.href = "/";
              }
              onTabChange?.("monitor");
            }}
            className={cn(
              "inline-flex items-center gap-1.5 rounded-md px-3 py-1.5 text-xs font-medium transition-colors",
              !isAssistant && activeTab === "monitor"
                ? "bg-background text-foreground shadow-sm"
                : "text-muted-foreground hover:text-foreground",
            )}
          >
            <Radio className="h-3.5 w-3.5" />
            Monitor
          </button>
          <Link
            href="/assistant"
            className={cn(
              "inline-flex items-center gap-1.5 rounded-md px-3 py-1.5 text-xs font-medium transition-colors",
              isAssistant
                ? "bg-background text-foreground shadow-sm"
                : "text-muted-foreground hover:text-foreground",
            )}
          >
            <BotMessageSquare className="h-3.5 w-3.5" />
            Assistant
          </Link>
        </nav>

        <div className="w-14" />
      </div>
    </header>
  );
}
