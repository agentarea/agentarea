/**
 * Scroll the timeline to the tool call with the given id and briefly flash it.
 * Timeline tool messages render with `id="tc-<tool_call_id>"`; grouped calls
 * also expose `data-aa-tc` listing every contained id (the group may be
 * collapsed, so the individual row id may not be in the DOM).
 */
export function scrollToToolCall(callId?: string | null): void {
  if (!callId || typeof document === "undefined") return;

  const escaped = typeof CSS !== "undefined" && CSS.escape ? CSS.escape(callId) : callId;
  const el =
    document.getElementById(`tc-${callId}`) ||
    document.querySelector<HTMLElement>(`[data-aa-tc~="${escaped}"]`);

  if (!el) return;

  el.scrollIntoView({ behavior: "smooth", block: "center" });

  // Brief flash via inline styles (no global CSS / no Tailwind purge concerns).
  const prev = {
    transition: el.style.transition,
    boxShadow: el.style.boxShadow,
    backgroundColor: el.style.backgroundColor,
    borderRadius: el.style.borderRadius,
  };
  el.style.borderRadius = el.style.borderRadius || "0.5rem";
  el.style.transition = "box-shadow 1.2s ease-out, background-color 1.2s ease-out";
  el.style.boxShadow = "0 0 0 2px rgba(59, 130, 246, 0.7)";
  el.style.backgroundColor = "rgba(59, 130, 246, 0.10)";

  window.requestAnimationFrame(() => {
    el.style.boxShadow = "0 0 0 2px rgba(59, 130, 246, 0)";
    el.style.backgroundColor = "transparent";
  });

  window.setTimeout(() => {
    el.style.transition = prev.transition;
    el.style.boxShadow = prev.boxShadow;
    el.style.backgroundColor = prev.backgroundColor;
    el.style.borderRadius = prev.borderRadius;
  }, 1300);
}
