"use client";

import { User, Bot } from "lucide-react";
import { MarkdownRenderer } from "./markdown-renderer";
import { ToolCallCard } from "./tool-call-card";
import type { ChatMessage as ChatMessageType } from "@/types";
import { cn } from "@/lib/utils";

interface ChatMessageProps {
  message: ChatMessageType;
}

export function ChatMessage({ message }: ChatMessageProps) {
  const isUser = message.role === "user";

  return (
    <div
      className={cn(
        "flex gap-3 px-4 py-3",
        isUser ? "flex-row-reverse" : "flex-row",
      )}
    >
      <div
        className={cn(
          "flex h-7 w-7 shrink-0 items-center justify-center rounded-full",
          isUser
            ? "bg-primary text-primary-foreground"
            : "bg-muted text-muted-foreground",
        )}
      >
        {isUser ? (
          <User className="h-3.5 w-3.5" />
        ) : (
          <Bot className="h-3.5 w-3.5" />
        )}
      </div>

      <div
        className={cn("min-w-0 max-w-[85%] space-y-2", isUser && "text-right")}
      >
        {isUser ? (
          <div className="inline-block rounded-2xl rounded-tr-sm bg-primary px-4 py-2.5 text-sm text-primary-foreground">
            {message.content}
          </div>
        ) : (
          <>
            {message.content && (
              <div className="rounded-2xl rounded-tl-sm bg-muted/60 px-4 py-3">
                <MarkdownRenderer content={message.content} />
                {message.isStreaming && !message.tool_calls.length && (
                  <span className="inline-block h-4 w-1.5 animate-cursor-blink bg-foreground/70" />
                )}
              </div>
            )}

            {message.tool_calls.map((tc) => (
              <ToolCallCard key={tc.tool_call_id} toolCall={tc} />
            ))}

            {message.isStreaming &&
              !message.content &&
              message.tool_calls.length === 0 && (
                <div className="rounded-2xl rounded-tl-sm bg-muted/60 px-4 py-3">
                  <span className="inline-block h-4 w-1.5 animate-cursor-blink bg-foreground/70" />
                </div>
              )}
          </>
        )}
      </div>
    </div>
  );
}
