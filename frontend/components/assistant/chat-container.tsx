"use client";

import { useEffect, useRef } from "react";
import { ScrollArea } from "@/components/ui/scroll-area";
import { ChatMessage } from "./chat-message";
import { ChatInput } from "./chat-input";
import type { ChatMessage as ChatMessageType } from "@/types";
import { AlertCircle } from "lucide-react";

interface ChatContainerProps {
  messages: ChatMessageType[];
  isConnected: boolean;
  isLoading: boolean;
  error: string | null;
  onSend: (text: string) => void;
  onReconnect: () => void;
}

export function ChatContainer({
  messages,
  isConnected,
  isLoading,
  error,
  onSend,
  onReconnect,
}: ChatContainerProps) {
  const bottomRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    bottomRef.current?.scrollIntoView({ behavior: "smooth" });
  }, [messages]);

  return (
    <div className="flex h-full flex-col">
      <ScrollArea className="flex-1">
        <div className="mx-auto max-w-3xl py-4">
          {messages.length === 0 && (
            <div className="flex h-[60vh] items-center justify-center">
              <div className="text-center space-y-2">
                <div className="font-mono text-lg font-bold tracking-wider text-foreground/15">
                  SCIOS Assistant
                </div>
                <p className="text-xs text-muted-foreground/50">
                  Ask anything about your research.
                </p>
              </div>
            </div>
          )}

          {messages.map((msg) => (
            <ChatMessage key={msg.id} message={msg} />
          ))}

          {error && (
            <div className="mx-4 my-2 flex items-center gap-2 rounded-lg bg-destructive/10 px-4 py-2.5 text-xs text-destructive">
              <AlertCircle className="h-3.5 w-3.5 shrink-0" />
              {error}
            </div>
          )}

          <div ref={bottomRef} className="h-px" />
        </div>
      </ScrollArea>

      <ChatInput
        onSend={onSend}
        isLoading={isLoading}
        isConnected={isConnected}
        onReconnect={onReconnect}
      />
    </div>
  );
}
