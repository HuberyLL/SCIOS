"use client";

import { useState } from "react";
import { Plus, Loader2 } from "lucide-react";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Button } from "@/components/ui/button";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import { createMonitorTask } from "@/lib/api";

interface SubscribeFormProps {
  onCreated: () => void;
}

export function SubscribeForm({ onCreated }: SubscribeFormProps) {
  const [topic, setTopic] = useState("");
  const [frequency, setFrequency] = useState<"daily" | "weekly">("daily");
  const [email, setEmail] = useState("");
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const handleSubmit = async () => {
    const trimmed = topic.trim();
    if (!trimmed || loading) return;
    setLoading(true);
    setError(null);

    try {
      await createMonitorTask({
        topic: trimmed,
        frequency,
        notify_email: email.trim() || null,
      });
      setTopic("");
      setEmail("");
      onCreated();
    } catch (e) {
      setError(e instanceof Error ? e.message : "Failed to create task");
    } finally {
      setLoading(false);
    }
  };

  return (
    <Card className="border-border/40">
      <CardHeader className="pb-4">
        <CardTitle className="text-sm font-semibold">New Subscription</CardTitle>
      </CardHeader>
      <CardContent className="space-y-4">
        <div className="space-y-1.5">
          <Label htmlFor="monitor-topic" className="text-xs">
            Topic
          </Label>
          <Input
            id="monitor-topic"
            value={topic}
            onChange={(e) => setTopic(e.target.value)}
            placeholder="e.g. LLM reasoning"
            className="h-9 text-sm"
            onKeyDown={(e) => e.key === "Enter" && handleSubmit()}
          />
        </div>

        <div className="space-y-1.5">
          <Label htmlFor="monitor-freq" className="text-xs">
            Frequency
          </Label>
          <Select
            value={frequency}
            onValueChange={(v) => setFrequency(v as "daily" | "weekly")}
          >
            <SelectTrigger id="monitor-freq" className="h-9 text-sm">
              <SelectValue />
            </SelectTrigger>
            <SelectContent>
              <SelectItem value="daily">Daily</SelectItem>
              <SelectItem value="weekly">Weekly</SelectItem>
            </SelectContent>
          </Select>
        </div>

        <div className="space-y-1.5">
          <Label htmlFor="monitor-email" className="text-xs">
            Email{" "}
            <span className="text-muted-foreground">(optional)</span>
          </Label>
          <Input
            id="monitor-email"
            type="email"
            value={email}
            onChange={(e) => setEmail(e.target.value)}
            placeholder="you@example.com"
            className="h-9 text-sm"
          />
        </div>

        {error && (
          <p className="text-xs text-destructive">{error}</p>
        )}

        <Button
          onClick={handleSubmit}
          disabled={!topic.trim() || loading}
          className="w-full gap-2"
          size="sm"
        >
          {loading ? (
            <Loader2 className="h-3.5 w-3.5 animate-spin" />
          ) : (
            <Plus className="h-3.5 w-3.5" />
          )}
          Subscribe
        </Button>
      </CardContent>
    </Card>
  );
}
