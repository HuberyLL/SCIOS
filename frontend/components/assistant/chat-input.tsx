"use client";

import { useCallback, useRef, useState, type KeyboardEvent } from "react";
import { Textarea } from "@/components/ui/textarea";
import { Button } from "@/components/ui/button";
import { SendHorizontal, Loader2, WifiOff } from "lucide-react";
import { cn } from "@/lib/utils";

interface ChatInputProps {
  onSend: (text: string) => void;
  isLoading: boolean;
  isConnected: boolean;
  onReconnect: () => void;
}

export function ChatInput({
  onSend,
  isLoading,
  isConnected,
  onReconnect,
}: ChatInputProps) {
  const [value, setValue] = useState("");
  const textareaRef = useRef<HTMLTextAreaElement>(null);

  const handleSend = useCallback(() => {
    const trimmed = value.trim();
    if (!trimmed || isLoading || !isConnected) return;
    onSend(trimmed);
    setValue("");
    if (textareaRef.current) {
      textareaRef.current.style.height = "auto";
    }
  }, [value, isLoading, isConnected, onSend]);

  const handleKeyDown = useCallback(
    (e: KeyboardEvent<HTMLTextAreaElement>) => {
      if (e.key === "Enter" && !e.shiftKey) {
        e.preventDefault();
        handleSend();
      }
    },
    [handleSend],
  );

  const handleInput = useCallback(() => {
    const el = textareaRef.current;
    if (!el) return;
    el.style.height = "auto";
    const maxH = 6 * 24; // ~6 lines
    el.style.height = `${Math.min(el.scrollHeight, maxH)}px`;
  }, []);

  const disabled = !isConnected || isLoading;

  return (
    <div className="border-t border-border/40 bg-background px-4 py-3">
      {!isConnected && (
        <button
          onClick={onReconnect}
          className="mb-2 flex w-full items-center justify-center gap-2 rounded-md bg-destructive/10 px-3 py-1.5 text-xs text-destructive transition-colors hover:bg-destructive/20"
        >
          <WifiOff className="h-3.5 w-3.5" />
          Connection lost — click to reconnect
        </button>
      )}

      <div className="flex items-end gap-2">
        <Textarea
          ref={textareaRef}
          value={value}
          onChange={(e) => {
            setValue(e.target.value);
            handleInput();
          }}
          onKeyDown={handleKeyDown}
          placeholder={
            isConnected
              ? "Send a message... (Enter to send, Shift+Enter for newline)"
              : "Waiting for connection..."
          }
          disabled={!isConnected}
          rows={1}
          className={cn(
            "min-h-[40px] max-h-[144px] resize-none bg-muted/40 text-sm",
            "focus-visible:ring-1 focus-visible:ring-ring",
          )}
        />
        <Button
          size="icon"
          onClick={handleSend}
          disabled={disabled || !value.trim()}
          className="h-10 w-10 shrink-0"
        >
          {isLoading ? (
            <Loader2 className="h-4 w-4 animate-spin" />
          ) : (
            <SendHorizontal className="h-4 w-4" />
          )}
        </Button>
      </div>
    </div>
  );
}
