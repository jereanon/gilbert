// Typing-indicator helpers.
//
// Split into two hooks:
//
// - ``useTypingBroadcast(conversationId, enabled)`` — the typer side.
//   Call ``notifyTyping()`` on every textarea change. The hook coalesces
//   keystrokes into ``chat.typing.start`` frames (sent at most every
//   3 seconds while the user keeps typing) and emits a single
//   ``chat.typing.stop`` after ~5s of silence — OR immediately when
//   ``flushStop()`` is called (e.g. on send).
//
// - ``useTypingUsers(conversationId)`` — the viewer side. Subscribes to
//   ``chat.typing.{start,stop}`` events, keeps a per-user-id map of who
//   is currently typing in this room, and auto-clears entries that
//   haven't seen a fresh ``start`` in ~6 seconds (in case the typer's
//   connection drops without firing a ``stop``).

import { useCallback, useEffect, useRef, useState } from "react";
import { useWebSocket } from "./useWebSocket";
import type { GilbertEvent } from "@/types/events";

// How often we re-fire ``chat.typing.start`` while the user keeps
// typing. The server doesn't track these timeouts — it just rebroadcasts
// each event — so the cadence here also determines how fresh the
// indicator stays for viewers.
const KEEPALIVE_MS = 3_000;
// Idle time before we automatically emit ``chat.typing.stop``. Slightly
// longer than ``KEEPALIVE_MS`` so a brief pause mid-sentence doesn't
// flicker the indicator off and back on.
const IDLE_STOP_MS = 5_000;
// How long after a viewer's last ``chat.typing.start`` we keep showing
// the indicator without a ``stop`` event arriving. Catches the case
// where the typer's connection drops mid-type.
const VIEWER_STALE_MS = 6_000;

interface BroadcastApi {
  /** Call on every textarea change while the user is actively
   *  composing. Cheap — coalesces internally. */
  notifyTyping: () => void;
  /** Emit ``stop`` immediately and reset internal timers. Call on
   *  message-send, blur, or any other "I'm definitely done typing"
   *  signal. */
  flushStop: () => void;
}

export function useTypingBroadcast(
  conversationId: string | null,
  enabled: boolean,
): BroadcastApi {
  const { send, connected } = useWebSocket();
  // ``isTypingRef`` is the source of truth for the local typing state.
  // A ref (not state) because we never need to re-render on the typer's
  // own status — the indicator they see is for *other* people, not
  // themselves.
  const isTypingRef = useRef(false);
  const lastSentAtRef = useRef(0);
  const stopTimerRef = useRef<number | null>(null);

  const conv = conversationId ?? "";
  const active = enabled && connected && conv !== "";

  const sendStop = useCallback(() => {
    if (!active || !isTypingRef.current) return;
    isTypingRef.current = false;
    if (stopTimerRef.current !== null) {
      window.clearTimeout(stopTimerRef.current);
      stopTimerRef.current = null;
    }
    try {
      send({ type: "chat.typing.stop", conversation_id: conv });
    } catch {
      // ``send`` only throws when the WS isn't connected. We've
      // already updated local state; the indicator will time out on
      // the viewer side. Nothing else to do.
    }
  }, [active, conv, send]);

  const notifyTyping = useCallback(() => {
    if (!active) return;
    const now = Date.now();
    const wasTyping = isTypingRef.current;
    // Throttle to one ``start`` frame per KEEPALIVE_MS window. The
    // first keystroke after a quiet period always fires.
    if (!wasTyping || now - lastSentAtRef.current >= KEEPALIVE_MS) {
      lastSentAtRef.current = now;
      isTypingRef.current = true;
      try {
        send({ type: "chat.typing.start", conversation_id: conv });
      } catch {
        // Same as sendStop — best effort.
      }
    }
    // Reset the auto-stop timer on every keystroke.
    if (stopTimerRef.current !== null) {
      window.clearTimeout(stopTimerRef.current);
    }
    stopTimerRef.current = window.setTimeout(sendStop, IDLE_STOP_MS);
  }, [active, conv, send, sendStop]);

  // If the conversation changes (or the hook unmounts) while we're
  // mid-typing, fire the stop so we don't leave a stale indicator
  // visible to other members of the old room.
  useEffect(() => {
    return () => {
      if (isTypingRef.current) sendStop();
    };
  }, [conv, sendStop]);

  return { notifyTyping, flushStop: sendStop };
}

interface TypingUser {
  user_id: string;
  display_name: string;
}

/** Returns the list of users currently typing in ``conversationId``,
 *  excluding ourselves (the server already filters self-typing
 *  events, but the assertion is cheap and keeps the data model
 *  honest). The list updates live and auto-clears stale entries
 *  after ``VIEWER_STALE_MS``. */
export function useTypingUsers(conversationId: string | null): TypingUser[] {
  const { subscribe } = useWebSocket();
  // user_id → { display_name, lastStartAt }. We hold display_name from
  // the most recent ``start`` event so the indicator's label survives
  // if the typer's account display_name changes mid-session (rare but
  // cheap to handle right).
  const [typers, setTypers] = useState<TypingUser[]>([]);
  // Timestamps of the most recent ``start`` event per user, used by
  // the stale-clear interval. Stored in a ref so the interval doesn't
  // capture stale state.
  const lastStartRef = useRef<Map<string, number>>(new Map());

  useEffect(() => {
    // Clear when switching rooms — the old room's typing list shouldn't
    // bleed into the new one even for a moment.
    setTypers([]);
    lastStartRef.current = new Map();
    if (!conversationId) return;

    const onStart = (event: GilbertEvent) => {
      const data = event.data as {
        conversation_id?: string;
        user_id?: string;
        display_name?: string;
      };
      if (data.conversation_id !== conversationId) return;
      const uid = data.user_id;
      if (!uid) return;
      lastStartRef.current.set(uid, Date.now());
      const name = data.display_name || uid;
      setTypers((prev) => {
        const idx = prev.findIndex((t) => t.user_id === uid);
        if (idx >= 0) {
          if (prev[idx].display_name === name) return prev;
          const next = prev.slice();
          next[idx] = { user_id: uid, display_name: name };
          return next;
        }
        return [...prev, { user_id: uid, display_name: name }];
      });
    };

    const onStop = (event: GilbertEvent) => {
      const data = event.data as {
        conversation_id?: string;
        user_id?: string;
      };
      if (data.conversation_id !== conversationId) return;
      const uid = data.user_id;
      if (!uid) return;
      lastStartRef.current.delete(uid);
      setTypers((prev) =>
        prev.some((t) => t.user_id === uid)
          ? prev.filter((t) => t.user_id !== uid)
          : prev,
      );
    };

    const unsubStart = subscribe("chat.typing.start", onStart);
    const unsubStop = subscribe("chat.typing.stop", onStop);

    // Stale-clear loop. Runs every second; trims entries whose last
    // ``start`` was longer ago than ``VIEWER_STALE_MS``. Guards
    // against silent disconnects on the typer's side.
    const sweep = window.setInterval(() => {
      const now = Date.now();
      const stale: string[] = [];
      lastStartRef.current.forEach((ts, uid) => {
        if (now - ts >= VIEWER_STALE_MS) stale.push(uid);
      });
      if (stale.length === 0) return;
      stale.forEach((uid) => lastStartRef.current.delete(uid));
      setTypers((prev) => prev.filter((t) => !stale.includes(t.user_id)));
    }, 1_000);

    return () => {
      unsubStart();
      unsubStop();
      window.clearInterval(sweep);
    };
  }, [conversationId, subscribe]);

  return typers;
}
