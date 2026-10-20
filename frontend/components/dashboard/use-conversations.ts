"use client";

import { useCallback, useEffect, useState } from "react";
import {
  deleteConversation,
  listConversations,
  renameConversation,
  type ConversationSummary,
} from "@/lib/api";

const POLL_MS = 4000;

// No backend or no data yet: show the empty state.
const load = () => listConversations().catch((): ConversationSummary[] => []);

export function useConversations(enabled: boolean) {
  const [conversations, setConversations] = useState<ConversationSummary[]>([]);
  const [loaded, setLoaded] = useState(false);

  const refresh = useCallback(async () => {
    setConversations(await load());
    setLoaded(true);
  }, []);

  useEffect(() => {
    if (!enabled) return;
    let cancelled = false;
    load().then((list) => {
      if (cancelled) return;
      setConversations(list);
      setLoaded(true);
    });
    return () => {
      cancelled = true;
    };
  }, [enabled]);

  // Generated titles arrive a few seconds after the first answer.
  const titlePending = conversations.some((c) => c.title_pending);
  useEffect(() => {
    if (!titlePending) return;
    const timer = setInterval(refresh, POLL_MS);
    return () => clearInterval(timer);
  }, [titlePending, refresh]);

  // Throws so the caller can show the error next to the field.
  const rename = useCallback(async (id: string, title: string | null) => {
    const updated = await renameConversation(id, title);
    setConversations((all) => all.map((c) => (c.id === id ? updated : c)));
  }, []);

  const remove = useCallback(async (id: string) => {
    await deleteConversation(id);
    setConversations((all) => all.filter((c) => c.id !== id));
  }, []);

  return { conversations, loaded, refresh, rename, remove };
}
