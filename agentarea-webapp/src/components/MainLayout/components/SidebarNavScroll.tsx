"use client";

import * as React from "react";
import { SidebarContent } from "@/components/ui/sidebar";
import { cn } from "@/lib/utils";

/**
 * Scrollable nav region that softly fades its content where it meets the
 * fixed header, instead of hard-clipping it. The top fade is shown only when
 * there is content to scroll up to. There's no bottom fade — the footer's
 * divider line already separates that edge.
 */
export function SidebarNavScroll({
  children,
  className,
}: {
  children: React.ReactNode;
  className?: string;
}) {
  const scrollRef = React.useRef<HTMLDivElement>(null);
  const [showTop, setShowTop] = React.useState(false);

  const update = React.useCallback(() => {
    const el = scrollRef.current;
    if (!el) return;
    setShowTop(el.scrollTop > 1);
  }, []);

  React.useEffect(() => {
    const el = scrollRef.current;
    if (!el) return;
    update();
    // Recompute when the content height changes (e.g. groups expand/collapse).
    const observer = new ResizeObserver(update);
    observer.observe(el);
    for (const child of Array.from(el.children)) observer.observe(child);
    window.addEventListener("resize", update);
    return () => {
      observer.disconnect();
      window.removeEventListener("resize", update);
    };
  }, [update]);

  return (
    <div className="relative flex min-h-0 flex-1 flex-col">
      <SidebarContent
        ref={scrollRef}
        onScroll={update}
        className={className}
      >
        {children}
      </SidebarContent>
      <div
        aria-hidden
        className={cn(
          "pointer-events-none absolute inset-x-0 top-0 h-6 bg-gradient-to-b from-sidebar to-sidebar/0 transition-opacity duration-200",
          showTop ? "opacity-100" : "opacity-0"
        )}
      />
    </div>
  );
}
