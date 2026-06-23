"use client";

import { ArrowUpRight } from "lucide-react";
import type { KeyboardEvent, ReactNode } from "react";
import type { StatusTone } from "@/lib/status";
import { cn } from "@/lib/utils";

const DECORATION_TINT_STYLES = {
  success: "[background-image:var(--row-tint-success)]",
  warning: "[background-image:var(--row-tint-warning)]",
  danger: "[background-image:var(--row-tint-danger)]",
  info: "[background-image:var(--row-tint-info)]",
  neutral: "[background-image:var(--row-tint-neutral)]",
} satisfies Record<StatusTone, string>;

interface InteractiveListRowProps {
  children: ReactNode;
  start?: ReactNode;
  end?: ReactNode;
  hoverActions?: ReactNode;
  indicator?: ReactNode;
  onClick?: () => void;
  selected?: boolean;
  className?: string;
  dividerClassName?: string;
  contentClassName?: string;
  decorationTone?: StatusTone;
  decorationTintClassName?: string;
  decorationVisible?: boolean;
  hoverClassName?: string;
  selectedClassName?: string;
  endClassName?: string;
  hoverActionsClassName?: string;
  indicatorClassName?: string;
  forceHoverActionsVisible?: boolean;
  showIndicator?: boolean;
}

export function InteractiveListRow({
  children,
  start,
  end,
  hoverActions,
  indicator,
  onClick,
  selected = false,
  className,
  dividerClassName = "border-b border-zinc-200 dark:border-zinc-700",
  contentClassName,
  decorationTone,
  decorationTintClassName,
  decorationVisible = false,
  hoverClassName = "hover:bg-muted/60 dark:hover:bg-zinc-700/20",
  selectedClassName = "bg-muted/60 dark:bg-zinc-700/20",
  endClassName,
  hoverActionsClassName,
  indicatorClassName,
  forceHoverActionsVisible = false,
  showIndicator = true,
}: InteractiveListRowProps) {
  const isClickable = Boolean(onClick);
  const hasHoverState = showIndicator || Boolean(hoverActions);

  function handleKeyDown(event: KeyboardEvent<HTMLDivElement>) {
    if (!onClick) return;
    if (event.key === "Enter" || event.key === " ") {
      event.preventDefault();
      onClick();
    }
  }

  return (
    <div
      role={isClickable ? "button" : undefined}
      tabIndex={isClickable ? 0 : undefined}
      onClick={onClick}
      onKeyDown={handleKeyDown}
      className={cn(
        "group relative flex min-w-0 items-center gap-3 overflow-hidden px-4 py-2.5 transition-colors",
        dividerClassName,
        isClickable && "cursor-pointer",
        selected ? selectedClassName : hoverClassName,
        className
      )}
    >
      <span
        aria-hidden
        className="pointer-events-none absolute inset-y-0 right-0 z-0 w-[230px] translate-x-[14px] opacity-0 [-webkit-mask-image:linear-gradient(90deg,transparent,#000_82%)] [background-image:var(--hatch-accent)] [mask-image:linear-gradient(90deg,transparent,#000_82%)] transition-[opacity,transform] duration-300 ease-[cubic-bezier(0.4,0,0.2,1)] group-hover:translate-x-0 group-hover:opacity-[0.85]"
      />
      <span
        aria-hidden
        data-visible={decorationVisible || undefined}
        className={cn(
          "pointer-events-none absolute inset-y-0 right-0 z-0 w-[230px] translate-x-[14px] opacity-0 [-webkit-mask-image:linear-gradient(90deg,transparent,#000_82%)] [mask-image:linear-gradient(90deg,transparent,#000_82%)] transition-[opacity,transform] duration-300 ease-[cubic-bezier(0.4,0,0.2,1)] data-[visible=true]:translate-x-0 data-[visible=true]:opacity-100",
          decorationTone ? DECORATION_TINT_STYLES[decorationTone] : undefined,
          decorationTintClassName
        )}
      />

      {start ? <span className="relative z-[1] flex shrink-0">{start}</span> : null}

      <div
        className={cn(
          "relative z-[1] flex min-w-0 flex-1 items-center",
          contentClassName
        )}
      >
        {children}
      </div>

      {end ? (
        <span
          className={cn(
            "relative z-[1] flex shrink-0 items-center gap-2",
            hasHoverState &&
              "group-hover:invisible data-[hover-actions-visible=true]:invisible",
            endClassName
          )}
          data-hover-actions-visible={forceHoverActionsVisible || undefined}
        >
          {end}
        </span>
      ) : null}

      {hoverActions ? (
        <span
          className={cn(
            "absolute right-10 z-[2] flex h-full items-center gap-0.5 pl-8 transition-opacity",
            forceHoverActionsVisible
              ? "opacity-100"
              : "pointer-events-none opacity-0 group-hover:pointer-events-auto group-hover:opacity-100",
            hoverActionsClassName
          )}
        >
          {hoverActions}
        </span>
      ) : null}

      {showIndicator ? (
        <span
          className={cn(
            "pointer-events-none absolute right-3 z-[2] grid h-[22px] w-[22px] place-items-center text-primary opacity-0 translate-x-1 transition-[opacity,transform] duration-200 ease-out",
            forceHoverActionsVisible
              ? "opacity-100 translate-x-0"
              : "group-hover:opacity-100 group-hover:translate-x-0",
            indicatorClassName
          )}
          aria-hidden
        >
          {indicator ?? <ArrowUpRight className="h-4 w-4" strokeWidth={2} />}
        </span>
      ) : null}
    </div>
  );
}
