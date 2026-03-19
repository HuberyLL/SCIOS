"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import { assistantWsUrl, getAssistantSession } from "@/lib/api";
import type {
  Artifact,
  ArtifactType,
  AssistantMessageOut,
  AssistantWSEvent,
  ChatMessage,
  ToolCallBlock,
} from "@/types";

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

const ARTIFACT_PATTERNS: { regex: RegExp; type: ArtifactType }[] = [
  { regex: /(?:^|\s)([\w/.=-]+\.pdf)\b/i, type: "pdf" },
  { regex: /(?:^|\s)([\w/.=-]+\.(?:png|jpg|jpeg|gif|svg|webp))\b/i, type: "image" },
  { regex: /(?:^|\s)([\w/.=-]+\.(?:py|ts|js|tsx|jsx|sh|r|tex|csv))\b/i, type: "code" },
];

function detectArtifact(toolName: string, result: string): Artifact | null {
  for (const { regex, type } of ARTIFACT_PATTERNS) {
    const match = result.match(regex);
    if (match) {
      const path = match[1];
      return { type, path, label: `${toolName}: ${path}` };
    }
  }
  return null;
}

function convertHistoryMessages(msgs: AssistantMessageOut[]): ChatMessage[] {
  const result: ChatMessage[] = [];
  const toolResultMap = new Map<string, string>();

  for (const m of msgs) {
    if (m.role === "tool" && m.tool_call_id) {
      toolResultMap.set(m.tool_call_id, m.content);
    }
  }

  for (const m of msgs) {
    if (m.role === "user") {
      result.push({
        id: m.id,
        role: "user",
        content: m.content,
        tool_calls: [],
      });
    } else if (m.role === "assistant") {
      const toolCalls: ToolCallBlock[] = [];
      if (m.tool_calls) {
        for (const tc of m.tool_calls) {
          const fn = tc.function as
            | { name?: string; arguments?: string }
            | undefined;
          const tcId = (tc.id as string) || "";
          const name = fn?.name || "unknown";
          let args: Record<string, unknown> = {};
          try {
            args = fn?.arguments ? JSON.parse(fn.arguments as string) : {};
          } catch {
            /* ignore */
          }
          toolCalls.push({
            tool_call_id: tcId,
            tool_name: name,
            args,
            result: toolResultMap.get(tcId),
            status: toolResultMap.has(tcId) ? "completed" : "error",
          });
        }
      }
      result.push({
        id: m.id,
        role: "assistant",
        content: m.content,
        tool_calls: toolCalls,
      });
    }
  }
  return result;
}

let nextMsgId = 0;
function genId() {
  return `local-${Date.now()}-${nextMsgId++}`;
}

// ---------------------------------------------------------------------------
// Reconnect config
// ---------------------------------------------------------------------------

const MAX_RECONNECT = 5;
const BASE_DELAY_MS = 1000;

// ---------------------------------------------------------------------------
// Hook
// ---------------------------------------------------------------------------

export interface UseAssistantChatReturn {
  messages: ChatMessage[];
  activeArtifact: Artifact | null;
  setActiveArtifact: (a: Artifact | null) => void;
  isConnected: boolean;
  isLoading: boolean;
  error: string | null;
  sendMessage: (text: string) => void;
  reconnect: () => void;
}

export function useAssistantChat(
  sessionId: string | null,
): UseAssistantChatReturn {
  const [messages, setMessages] = useState<ChatMessage[]>([]);
  const [activeArtifact, setActiveArtifact] = useState<Artifact | null>(null);
  const [isConnected, setIsConnected] = useState(false);
  const [isLoading, setIsLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const wsRef = useRef<WebSocket | null>(null);
  const reconnectCount = useRef(0);
  const reconnectTimer = useRef<ReturnType<typeof setTimeout> | null>(null);
  const sessionIdRef = useRef(sessionId);
  sessionIdRef.current = sessionId;

  // Load history on session change
  useEffect(() => {
    if (!sessionId) {
      setMessages([]);
      setActiveArtifact(null);
      return;
    }
    let cancelled = false;
    getAssistantSession(sessionId)
      .then((data) => {
        if (cancelled) return;
        setMessages(convertHistoryMessages(data.messages));
      })
      .catch(() => {
        if (!cancelled) setMessages([]);
      });
    return () => {
      cancelled = true;
    };
  }, [sessionId]);

  // WebSocket connection management
  const connect = useCallback(() => {
    if (!sessionId) return;

    const prev = wsRef.current;
    if (prev && prev.readyState <= WebSocket.OPEN) {
      prev.close();
    }

    const url = assistantWsUrl(sessionId);
    const ws = new WebSocket(url);
    wsRef.current = ws;

    ws.onopen = () => {
      setIsConnected(true);
      setError(null);
      reconnectCount.current = 0;
    };

    ws.onclose = () => {
      setIsConnected(false);
      setIsLoading(false);
      if (sessionIdRef.current === sessionId) {
        scheduleReconnect();
      }
    };

    ws.onerror = () => {
      setIsConnected(false);
      setIsLoading(false);
    };

    ws.onmessage = (ev) => {
      try {
        const event = JSON.parse(ev.data) as AssistantWSEvent;
        handleEvent(event);
      } catch {
        /* malformed JSON */
      }
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [sessionId]);

  const scheduleReconnect = useCallback(() => {
    if (reconnectCount.current >= MAX_RECONNECT) {
      setError("Connection lost. Click to reconnect.");
      return;
    }
    const delay = BASE_DELAY_MS * Math.pow(2, reconnectCount.current);
    reconnectCount.current += 1;
    reconnectTimer.current = setTimeout(() => {
      if (sessionIdRef.current) connect();
    }, delay);
  }, [connect]);

  const handleEvent = useCallback((event: AssistantWSEvent) => {
    switch (event.event) {
      case "text_delta": {
        const delta = event.data.content;
        setMessages((prev) => {
          const msgs = [...prev];
          const last = msgs[msgs.length - 1];
          if (last?.role === "assistant" && last.isStreaming) {
            msgs[msgs.length - 1] = {
              ...last,
              content: last.content + delta,
            };
          } else {
            msgs.push({
              id: genId(),
              role: "assistant",
              content: delta,
              tool_calls: [],
              isStreaming: true,
            });
          }
          return msgs;
        });
        break;
      }

      case "tool_call_start": {
        const { tool_name, tool_call_id, tool_args } = event.data;
        setMessages((prev) => {
          const msgs = [...prev];
          const last = msgs[msgs.length - 1];
          if (last?.role === "assistant" && last.isStreaming) {
            msgs[msgs.length - 1] = {
              ...last,
              tool_calls: [
                ...last.tool_calls,
                {
                  tool_call_id,
                  tool_name,
                  args: tool_args,
                  status: "running",
                },
              ],
            };
          }
          return msgs;
        });
        break;
      }

      case "tool_call_result": {
        const { tool_name, tool_call_id, result } = event.data;
        setMessages((prev) => {
          const msgs = [...prev];
          const last = msgs[msgs.length - 1];
          if (last?.role === "assistant" && last.isStreaming) {
            msgs[msgs.length - 1] = {
              ...last,
              tool_calls: last.tool_calls.map((tc) =>
                tc.tool_call_id === tool_call_id
                  ? { ...tc, status: "completed" as const, result }
                  : tc,
              ),
            };
          }
          return msgs;
        });

        const artifact = detectArtifact(tool_name, result);
        if (artifact) setActiveArtifact(artifact);
        break;
      }

      case "message_complete": {
        setMessages((prev) => {
          const msgs = [...prev];
          const last = msgs[msgs.length - 1];
          if (last?.role === "assistant" && last.isStreaming) {
            msgs[msgs.length - 1] = {
              ...last,
              content: event.data.content || last.content,
              isStreaming: false,
            };
          }
          return msgs;
        });
        setIsLoading(false);
        break;
      }

      case "error": {
        setMessages((prev) => {
          const msgs = [...prev];
          const last = msgs[msgs.length - 1];
          if (last?.role === "assistant" && last.isStreaming) {
            msgs[msgs.length - 1] = { ...last, isStreaming: false };
          }
          return msgs;
        });
        setError(event.data.message);
        setIsLoading(false);
        break;
      }
    }
  }, []);

  // Connect / disconnect lifecycle
  useEffect(() => {
    connect();
    return () => {
      if (reconnectTimer.current) clearTimeout(reconnectTimer.current);
      wsRef.current?.close();
      wsRef.current = null;
      setIsConnected(false);
    };
  }, [connect]);

  const sendMessage = useCallback(
    (text: string) => {
      if (!wsRef.current || wsRef.current.readyState !== WebSocket.OPEN) return;
      const trimmed = text.trim();
      if (!trimmed) return;

      setMessages((prev) => [
        ...prev,
        { id: genId(), role: "user", content: trimmed, tool_calls: [] },
      ]);
      setIsLoading(true);
      setError(null);
      wsRef.current.send(JSON.stringify({ content: trimmed }));
    },
    [],
  );

  const reconnect = useCallback(() => {
    reconnectCount.current = 0;
    setError(null);
    connect();
  }, [connect]);

  return {
    messages,
    activeArtifact,
    setActiveArtifact,
    isConnected,
    isLoading,
    error,
    sendMessage,
    reconnect,
  };
}
