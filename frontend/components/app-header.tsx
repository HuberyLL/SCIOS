"use client";

import Link from "next/link";
import { usePathname, useSearchParams } from "next/navigation";
import { Telescope, Radio, BotMessageSquare } from "lucide-react";
import { cn } from "@/lib/utils";

export function AppHeader() {
  const pathname = usePathname();
  const searchParams = useSearchParams();
  const isAssistant = pathname?.startsWith("/assistant");
  const isHome = pathname === "/";
  const tab = searchParams.get("tab");

  const isExplore = isHome && tab === "explore";
  const isMonitor = isHome && tab === "monitor";

  return (
    <header className="sticky top-0 z-50 w-full border-b border-border/40 bg-background/80 backdrop-blur-sm">
      <div className="mx-auto flex h-14 max-w-7xl items-center justify-between px-6">
        <Link
          href="/assistant"
          className="select-none font-mono text-sm font-semibold tracking-widest uppercase text-foreground/80 hover:text-foreground transition-colors"
        >
          SCIOS
        </Link>

        <nav className="flex items-center gap-1 rounded-lg bg-muted/60 p-1">
          <Link
            href="/?tab=explore"
            className={cn(
              "inline-flex items-center gap-1.5 rounded-md px-3 py-1.5 text-xs font-medium transition-colors",
              isExplore
                ? "bg-background text-foreground shadow-sm"
                : "text-muted-foreground hover:text-foreground",
            )}
          >
            <Telescope className="h-3.5 w-3.5" />
            Explore
          </Link>
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
          <Link
            href="/?tab=monitor"
            className={cn(
              "inline-flex items-center gap-1.5 rounded-md px-3 py-1.5 text-xs font-medium transition-colors",
              isMonitor
                ? "bg-background text-foreground shadow-sm"
                : "text-muted-foreground hover:text-foreground",
            )}
          >
            <Radio className="h-3.5 w-3.5" />
            Monitor
          </Link>
        </nav>

        <div className="w-14" />
      </div>
    </header>
  );
}
