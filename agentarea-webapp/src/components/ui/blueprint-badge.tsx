import * as React from "react";
import { cn } from "@/lib/utils";

export type BlueprintBadgeVariant = "corners" | "crop" | "bracket";

/**
 * Small "blueprint" annotation used to tag the current user ("YOU") in people
 * lists: primary-colored caps with drafting marks around it, so it reads as a
 * note on the drawing rather than a status pill.
 */
export function BlueprintBadge({
  variant = "bracket",
  className,
  children,
  ...props
}: React.HTMLAttributes<HTMLSpanElement> & {
  variant?: BlueprintBadgeVariant;
}) {
  return (
    <span
      className={cn(
        "relative inline-flex shrink-0 items-center text-[8px] font-medium uppercase leading-[11px] tracking-[0.08em] text-primary",
        variant === "corners" && "px-[5px] py-[2px]",
        variant === "crop" && "gap-[5px]",
        variant === "bracket" && "px-[5px] py-px",
        className
      )}
      {...props}
    >
      {variant === "corners" && (
        <>
          <Mark className="-left-px -top-px h-[4px] w-[4px] border-l border-t" />
          <Mark className="-right-px -top-px h-[4px] w-[4px] border-r border-t" />
          <Mark className="-bottom-px -left-px h-[4px] w-[4px] border-b border-l" />
          <Mark className="-bottom-px -right-px h-[4px] w-[4px] border-b border-r" />
        </>
      )}
      {variant === "bracket" && (
        <>
          <Mark className="bottom-0 left-0 top-0 w-[3px] border-b border-l border-t" />
          <Mark className="bottom-0 right-0 top-0 w-[3px] border-b border-r border-t" />
        </>
      )}
      {variant === "crop" && <Cross />}
      {children}
      {variant === "crop" && <Cross />}
    </span>
  );
}

function Mark({ className }: { className: string }) {
  return (
    <span
      aria-hidden="true"
      className={cn(
        "pointer-events-none absolute border-primary/70",
        className
      )}
    />
  );
}

/** Tiny crop-mark cross, drawn with two hairlines. */
function Cross() {
  return (
    <span
      aria-hidden="true"
      className="relative inline-block h-[7px] w-[7px] shrink-0 opacity-70"
    >
      <span className="absolute left-0 right-0 top-1/2 h-px -translate-y-1/2 bg-primary" />
      <span className="absolute bottom-0 top-0 left-1/2 w-px -translate-x-1/2 bg-primary" />
    </span>
  );
}
