"use client";

import { useEffect } from "react";

/**
 * Moves focus to the element with `targetId` and scrolls it into view when it
 * mounts. Key it by what was opened, so each new selection runs it again.
 */
export default function FocusOnMount({ targetId }: { targetId: string }) {
  useEffect(() => {
    const target = document.getElementById(targetId);
    if (!target) return;
    target.focus({ preventScroll: true });
    const reduceMotion = window.matchMedia(
      "(prefers-reduced-motion: reduce)"
    ).matches;
    target.scrollIntoView({
      block: "nearest",
      behavior: reduceMotion ? "auto" : "smooth",
    });
  }, [targetId]);

  return null;
}
