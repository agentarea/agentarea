"use client";

import { useId, useLayoutEffect, useRef, useState } from "react";
import { ChevronDown } from "lucide-react";
import { HoverLink } from "@/components/ui/hover-link";
import { cn } from "@/lib/utils";

/**
 * One-line entity description with a "Show more" toggle that only appears when
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
  const descriptionId = useId();
  const [open, setOpen] = useState(false);
  const [overflows, setOverflows] = useState(false);
  const toggleLabel = open ? showLessLabel : showMoreLabel;

  useLayoutEffect(() => {
    const el = ref.current;
    if (!el || open) return;

    const checkOverflow = () =>
      setOverflows(el.scrollHeight - el.clientHeight > 2);
    const resizeObserver = new ResizeObserver(checkOverflow);

    checkOverflow();
    resizeObserver.observe(el);
    return () => resizeObserver.disconnect();
  }, [open, text]);

  return (
    <div className="mt-0.5 flex w-fit max-w-[700px] items-start gap-1">
      <p
        id={descriptionId}
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
          aria-expanded={open}
          aria-controls={descriptionId}
          aria-label={toggleLabel}
          onClick={() => setOpen((v) => !v)}
          className="group -mt-0.5 shrink-0 rounded-sm py-0.5 focus-visible:outline-none focus-visible:ring-1 focus-visible:ring-ring focus-visible:ring-offset-2"
        >
          <HoverLink
            text={toggleLabel}
            leadingIcon={
              <ChevronDown
                aria-hidden
                className={cn(
                  "h-[17px] w-[17px] transition-transform duration-300 motion-reduce:transition-none group-hover:scale-110 group-focus-visible:scale-110",
                  open && "rotate-180"
                )}
                strokeWidth={1.5}
              />
            }
          />
        </button>
      )}
    </div>
  );
}
