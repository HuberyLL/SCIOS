"use client";

import { useState } from "react";
import { motion } from "framer-motion";
import { Search, Sparkles } from "lucide-react";
import { Input } from "@/components/ui/input";
import { Button } from "@/components/ui/button";

interface SearchHeroProps {
  onSearch: (topic: string) => void;
  loading?: boolean;
}

export function SearchHero({ onSearch, loading }: SearchHeroProps) {
  const [topic, setTopic] = useState("");

  const handleSubmit = () => {
    const trimmed = topic.trim();
    if (trimmed && !loading) onSearch(trimmed);
  };

  return (
    <motion.div
      initial={{ opacity: 0, y: 30 }}
      animate={{ opacity: 1, y: 0 }}
      transition={{ duration: 0.5, ease: "easeOut" }}
      className="flex min-h-[calc(100vh-3.5rem)] flex-col items-center justify-center px-6"
    >
      <div className="mb-10 text-center">
        <h1 className="mb-3 text-4xl font-bold tracking-tight text-foreground sm:text-5xl">
          Topic Exploration
        </h1>
        <p className="max-w-lg text-base leading-relaxed text-muted-foreground">
          Enter a research topic. SCIOS will retrieve papers, identify key
          scholars, and synthesize a structured report for you.
        </p>
      </div>

      <div className="flex w-full max-w-2xl items-center gap-3">
        <div className="relative flex-1">
          <Search className="absolute left-3.5 top-1/2 h-4 w-4 -translate-y-1/2 text-muted-foreground" />
          <Input
            value={topic}
            onChange={(e) => setTopic(e.target.value)}
            onKeyDown={(e) => e.key === "Enter" && handleSubmit()}
            placeholder="e.g. Transformer architectures for time-series forecasting"
            className="h-12 pl-10 text-sm"
            disabled={loading}
          />
        </div>
        <Button
          onClick={handleSubmit}
          disabled={!topic.trim() || loading}
          className="h-12 gap-2 px-6"
        >
          <Sparkles className="h-4 w-4" />
          Explore
        </Button>
      </div>

      <p className="mt-4 text-xs text-muted-foreground/60">
        Press Enter to start &middot; Powered by Semantic Scholar &amp; LLM
      </p>
    </motion.div>
  );
}
