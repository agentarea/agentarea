"use client";

import { useEffect, useRef, useState } from "react";

/**
 * Calls `onVisible` when the element given the returned ref scrolls into view:
 * the sentinel at the end of an infinite list. It re-arms whenever `enabled`
 * turns back on, so a page too short to fill the screen still pulls the next.
 */
export function useOnVisible<T extends Element = HTMLDivElement>(
  onVisible: () => void,
  {
    enabled = true,
    rootMargin = "200px",
  }: { enabled?: boolean; rootMargin?: string } = {}
) {
  const [node, setNode] = useState<T | null>(null);
  const callback = useRef(onVisible);

  useEffect(() => {
    callback.current = onVisible;
  });

  useEffect(() => {
    if (!node || !enabled) return;
    const observer = new IntersectionObserver(
      (entries) => {
        if (entries[0]?.isIntersecting) callback.current();
      },
      { rootMargin }
    );
    observer.observe(node);
    return () => observer.disconnect();
  }, [node, enabled, rootMargin]);

  return setNode;
}
