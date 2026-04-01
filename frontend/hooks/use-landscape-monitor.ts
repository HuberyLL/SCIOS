"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import {
  getSubscription,
  getLandscapeIncrements,
  subscribeLandscape,
  unsubscribeLandscape,
  landscapeMonitorStreamUrl,
  type IncrementEntry,
} from "@/lib/api";
import type { LandscapeIncrement, LandscapeMonitorSSEEvent } from "@/types";

export interface LandscapeMonitorState {
  subscribed: boolean;
  subscriptionId: string | null;
  loading: boolean;
  pendingIncrements: IncrementEntry[];
}

const CURSOR_KEY_PREFIX = "landscape-monitor:last-seen:";

function hasIncrementDelta(increment: LandscapeIncrement): boolean {
  return (
    increment.new_papers.length > 0 ||
    increment.new_tech_nodes.length > 0 ||
    increment.new_tech_edges.length > 0 ||
    increment.new_scholars.length > 0 ||
    increment.new_collab_edges.length > 0 ||
    increment.new_comparisons.length > 0 ||
    increment.new_gaps.length > 0
  );
}

function cursorKey(topic: string): string {
  return `${CURSOR_KEY_PREFIX}${topic}`;
}

export function useLandscapeMonitor(topic: string | null) {
  const [state, setState] = useState<LandscapeMonitorState>({
    subscribed: false,
    subscriptionId: null,
    loading: false,
    pendingIncrements: [],
  });
  const esRef = useRef<EventSource | null>(null);
  const seenIncrementIdsRef = useRef<Set<string>>(new Set());
  const sinceCursorRef = useRef<string | null>(null);

  // Check subscription status on mount / topic change
  useEffect(() => {
    if (!topic) return;
    const currentTopic = topic;
    let cancelled = false;
    seenIncrementIdsRef.current = new Set();
    try {
      sinceCursorRef.current = localStorage.getItem(cursorKey(currentTopic));
    } catch {
      sinceCursorRef.current = null;
    }

    async function check() {
      setState((s) => ({ ...s, loading: true }));
      try {
        const res = await getSubscription(currentTopic);
        if (cancelled) return;
        if (res.subscribed && res.data) {
          const subscription = res.data;
          setState((s) => ({
            ...s,
            subscribed: true,
            subscriptionId: subscription.id,
            loading: false,
          }));
          const increments = await getLandscapeIncrements(
            currentTopic,
            sinceCursorRef.current || undefined,
          );
          if (cancelled) return;
          const fresh = increments.filter((e) => {
            if (!hasIncrementDelta(e.increment)) return false;
            if (seenIncrementIdsRef.current.has(e.id)) return false;
            seenIncrementIdsRef.current.add(e.id);
            return true;
          });
          setState((s) => ({
            ...s,
            pendingIncrements: fresh,
          }));
        } else {
          setState((s) => ({
            ...s,
            subscribed: false,
            subscriptionId: null,
            loading: false,
            pendingIncrements: [],
          }));
        }
      } catch {
        if (!cancelled) setState((s) => ({ ...s, loading: false }));
      }
    }

    check();
    return () => {
      cancelled = true;
    };
  }, [topic]);

  // SSE listener for increment_ready events
  useEffect(() => {
    if (!topic || !state.subscribed) return;

    const es = new EventSource(landscapeMonitorStreamUrl());
    esRef.current = es;

    es.onmessage = (event) => {
      try {
        const data = JSON.parse(event.data) as LandscapeMonitorSSEEvent;
        if (
          data.type === "increment_ready" &&
          data.topic === topic
        ) {
          if (!hasIncrementDelta(data.increment)) return;
          if (seenIncrementIdsRef.current.has(data.increment_id)) return;
          seenIncrementIdsRef.current.add(data.increment_id);
          setState((s) => ({
            ...s,
            pendingIncrements: [
              ...s.pendingIncrements,
              {
                id: data.increment_id,
                task_id: data.task_id,
                increment: data.increment,
                created_at: data.at,
              },
            ],
          }));
        }
      } catch {
        // malformed JSON — ignore
      }
    };

    es.onerror = () => {
      es.close();
    };

    return () => {
      es.close();
      esRef.current = null;
    };
  }, [topic, state.subscribed]);

  const subscribe = useCallback(async () => {
    if (!topic) return;
    setState((s) => ({ ...s, loading: true }));
    try {
      const res = await subscribeLandscape(topic);
      setState((s) => ({
        ...s,
        subscribed: true,
        subscriptionId: res.id,
        loading: false,
      }));
    } catch {
      setState((s) => ({ ...s, loading: false }));
    }
  }, [topic]);

  const unsubscribe = useCallback(async () => {
    if (!state.subscriptionId) return;
    setState((s) => ({ ...s, loading: true }));
    try {
      await unsubscribeLandscape(state.subscriptionId);
      setState((s) => ({
        ...s,
        subscribed: false,
        subscriptionId: null,
        loading: false,
        pendingIncrements: [],
      }));
    } catch {
      setState((s) => ({ ...s, loading: false }));
    }
  }, [state.subscriptionId]);

  const clearIncrements = useCallback(() => {
    setState((s) => {
      const latestCreatedAt = s.pendingIncrements.reduce<string | null>(
        (maxTs, item) => {
          if (!maxTs) return item.created_at;
          return item.created_at > maxTs ? item.created_at : maxTs;
        },
        null,
      );
      if (latestCreatedAt && topic) {
        sinceCursorRef.current = latestCreatedAt;
        try {
          localStorage.setItem(cursorKey(topic), latestCreatedAt);
        } catch {
          // ignore storage failures (e.g. privacy mode)
        }
      }
      return { ...s, pendingIncrements: [] };
    });
  }, [topic]);

  return {
    ...state,
    subscribe,
    unsubscribe,
    clearIncrements,
  };
}
