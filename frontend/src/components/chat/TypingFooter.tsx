// "X is typing…" footer for a shared conversation.
//
// Reads from ``useTypingUsers``; renders nothing when no one is
// typing. The label format escalates with crowd size:
//
//   1 typer  → "Dylan is typing…"
//   2 typers → "Dylan and Alice are typing…"
//   3+       → "Dylan, Alice and 2 others are typing…"
//
// The "…" is a real ellipsis character (U+2026), not three dots, so
// screen readers don't read "dot dot dot" and the visual sits flush
// with the baseline.

import { useTypingUsers } from "@/hooks/useTyping";

interface TypingFooterProps {
  conversationId: string;
}

export function TypingFooter({ conversationId }: TypingFooterProps) {
  const typers = useTypingUsers(conversationId);
  if (typers.length === 0) return null;

  const label = formatTypingLabel(typers.map((t) => t.display_name));
  return (
    <div
      className="px-4 text-[11px] text-muted-foreground/80 italic flex items-center gap-1.5"
      // ``aria-live=polite`` so screen readers announce typing
      // transitions without preempting the user's current focus.
      aria-live="polite"
      aria-atomic="true"
    >
      {/* Three small dots that pulse in sequence — subtle "live" cue
          without animating the text itself (which would be distracting
          when read alongside actual messages). */}
      <span className="inline-flex gap-0.5" aria-hidden="true">
        <span className="size-1 rounded-full bg-muted-foreground/70 animate-pulse [animation-delay:0ms]" />
        <span className="size-1 rounded-full bg-muted-foreground/70 animate-pulse [animation-delay:150ms]" />
        <span className="size-1 rounded-full bg-muted-foreground/70 animate-pulse [animation-delay:300ms]" />
      </span>
      <span>{label}</span>
    </div>
  );
}

/** Pure formatter — exported for testing. */
export function formatTypingLabel(names: string[]): string {
  // Defensive: the empty-list case is handled by the caller returning
  // null, but covering it here too keeps the function total.
  if (names.length === 0) return "";
  if (names.length === 1) return `${names[0]} is typing…`;
  if (names.length === 2) return `${names[0]} and ${names[1]} are typing…`;
  const extras = names.length - 2;
  return `${names[0]}, ${names[1]} and ${extras} other${
    extras === 1 ? "" : "s"
  } are typing…`;
}
