"use client";

import { useLayoutEffect, useRef, useState } from "react";
import { cn } from "@/lib/utils";

/**
 * One-line agent description with a "Show more" toggle that only appears when
 * the text actually overflows its single line.
 */
export function HeroDescription({
  text,
  showMoreLabel,
  showLessLabel,
}: {
  text: string;
  showMoreLabel: string;
  showLessLabel: string;
}) {
  const ref = useRef<HTMLParagraphElement>(null);
  const [open, setOpen] = useState(false);
  const [overflows, setOverflows] = useState(false);

  useLayoutEffect(() => {
    const el = ref.current;
    if (!el || open) return;
    const check = () => setOverflows(el.scrollHeight - el.clientHeight > 2);
    check();
    window.addEventListener("resize", check);
    return () => window.removeEventListener("resize", check);
  }, [open, text]);

  return (
    <div className="mt-0.5 flex max-w-[700px] items-baseline gap-2">
      <p
        ref={ref}
        className={cn(
          "m-0 min-w-0 flex-1 text-[12.5px] text-muted-foreground [text-wrap:pretty]",
          !open && "line-clamp-1"
        )}
      >
        {text}
      </p>
      {(overflows || open) && (
        <button
          type="button"
          onClick={() => setOpen((v) => !v)}
          className="shrink-0 whitespace-nowrap text-[12px] font-semibold text-primary transition-colors hover:text-primary-hover dark:text-accent-foreground"
        >
          {open ? showLessLabel : showMoreLabel}
        </button>
      )}
    </div>
  );
}
