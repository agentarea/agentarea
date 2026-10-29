"use client";

import { useId, type CSSProperties, type ReactNode } from "react";
import { ArrowUpRight } from "lucide-react";
import { cn } from "@/lib/utils";

interface InteractiveListRowProps {
  children: ReactNode;
  start?: ReactNode;
  end?: ReactNode;
  hoverActions?: ReactNode;
  leadingAction?: ReactNode;
  leadingActionVisible?: boolean;
  indicator?: ReactNode;
  onClick?: () => void;
  selected?: boolean;
  /** For a clickable row that toggles something: announced as aria-pressed. */
  pressed?: boolean;
  className?: string;
  dividerClassName?: string;
  contentClassName?: string;
  decorationTintClassName?: string;
  decorationVisible?: boolean;
  hoverClassName?: string;
  selectedClassName?: string;
  endClassName?: string;
  hoverActionsClassName?: string;
  /**
   * Room the hover actions take at the row's right edge. While they show, the
   * content stops short of them instead of running under a backdrop.
   */
  hoverActionsWidth?: number;
  indicatorClassName?: string;
  forceHoverActionsVisible?: boolean;
  showIndicator?: boolean;
}

export function InteractiveListRow({
  children,
  start,
  end,
  hoverActions,
  leadingAction,
  leadingActionVisible = false,
  indicator,
  onClick,
  selected = false,
  pressed,
  className,
  dividerClassName = "border-b border-zinc-200 dark:border-zinc-700",
  contentClassName,
  decorationTintClassName,
  decorationVisible = false,
  hoverClassName = "hover:bg-muted/60 dark:hover:bg-zinc-700/20",
  selectedClassName = "bg-muted/60 dark:bg-zinc-700/20",
  endClassName,
  hoverActionsClassName,
  hoverActionsWidth = 130,
  indicatorClassName,
  forceHoverActionsVisible = false,
  showIndicator = true,
}: InteractiveListRowProps) {
  const isClickable = Boolean(onClick);
  const hasHoverState = showIndicator || Boolean(hoverActions);
  const startId = useId();
  const contentId = useId();
  const endId = useId();
  const labelIds = [
    ...(start ? [startId] : []),
    contentId,
    ...(end ? [endId] : []),
  ].join(" ");
  const hiddenActionsClassName =
    "invisible pointer-events-none opacity-0 group-hover:visible group-hover:pointer-events-auto group-hover:opacity-100 group-has-[:focus-visible]:visible group-has-[:focus-visible]:pointer-events-auto group-has-[:focus-visible]:opacity-100 max-[767px]:visible max-[767px]:pointer-events-auto max-[767px]:opacity-100 [@media(hover:none)]:visible [@media(hover:none)]:pointer-events-auto [@media(hover:none)]:opacity-100";

  return (
    <div
      style={
        hoverActions
          ? ({
              "--row-actions": `${hoverActionsWidth}px`,
            } as CSSProperties)
          : undefined
      }
      className={cn(
        "group relative flex min-w-0 items-center gap-3 overflow-hidden px-4 py-2.5 transition-colors motion-reduce:transition-none",
        dividerClassName,
        isClickable && "cursor-pointer",
        selected ? selectedClassName : hoverClassName,
        className
      )}
    >
      {isClickable ? (
        <button
          type="button"
          aria-labelledby={labelIds}
          aria-pressed={pressed}
          onClick={onClick}
          className="absolute inset-0 z-0 cursor-pointer border-0 bg-transparent p-0 text-left focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring focus-visible:ring-inset"
        />
      ) : null}

      <span
        aria-hidden
        className="pointer-events-none absolute inset-y-0 right-0 z-0 w-[230px] translate-x-[14px] opacity-0 [-webkit-mask-image:linear-gradient(90deg,transparent,#000_82%)] [background-image:var(--hatch-accent)] [mask-image:linear-gradient(90deg,transparent,#000_82%)] transition-[opacity,transform] duration-300 ease-[cubic-bezier(0.4,0,0.2,1)] group-hover:translate-x-0 group-hover:opacity-[0.85] motion-reduce:transition-none"
      />
      <span
        aria-hidden
        data-visible={decorationVisible || undefined}
        className={cn(
          "pointer-events-none absolute inset-y-0 right-0 z-0 w-[230px] translate-x-[14px] opacity-0 [-webkit-mask-image:linear-gradient(90deg,transparent,#000_82%)] [mask-image:linear-gradient(90deg,transparent,#000_82%)] transition-[opacity,transform] duration-300 ease-[cubic-bezier(0.4,0,0.2,1)] data-[visible=true]:translate-x-0 data-[visible=true]:opacity-100 motion-reduce:transition-none",
          decorationTintClassName
        )}
      />

      {start ? (
        <span
          id={startId}
          aria-hidden={isClickable || undefined}
          className={cn(
            "relative z-[1] flex shrink-0",
            isClickable && "pointer-events-none"
          )}
        >
          {start}
        </span>
      ) : null}

      <div
        id={contentId}
        aria-hidden={isClickable || undefined}
        className={cn(
          "relative z-[1] flex min-w-0 flex-1 items-center",
          isClickable && "pointer-events-none",
          // Where the actions always show (a phone, no hover), the content
          // always leaves them room; elsewhere only while they show, and only
          // when no `end` slot is there for them to cover instead.
          hoverActions &&
            "max-[767px]:mr-[var(--row-actions)] [@media(hover:none)]:mr-[var(--row-actions)]",
          hoverActions &&
            !end &&
            "group-hover:mr-[var(--row-actions)] group-has-[:focus-visible]:mr-[var(--row-actions)]",
          hoverActions &&
            forceHoverActionsVisible &&
            !end &&
            "mr-[var(--row-actions)]",
          contentClassName
        )}
      >
        {children}
      </div>

      {end ? (
        <span
          id={endId}
          aria-hidden={isClickable || undefined}
          className={cn(
            "relative z-[1] flex shrink-0 items-center gap-2",
            isClickable && "pointer-events-none",
            hasHoverState &&
              "group-hover:invisible group-has-[:focus-visible]:invisible data-[hover-actions-visible=true]:invisible",
            hoverActions &&
              "max-[767px]:invisible [@media(hover:none)]:invisible",
            endClassName
          )}
          data-hover-actions-visible={forceHoverActionsVisible || undefined}
        >
          {end}
        </span>
      ) : null}

      {leadingAction ? (
        <span
          className={cn(
            "absolute left-3 top-[6px] z-[2] grid place-items-center",
            leadingActionVisible || forceHoverActionsVisible
              ? "visible pointer-events-auto opacity-100"
              : hiddenActionsClassName,
            "max-[767px]:left-[-2px] max-[767px]:top-[-8px]"
          )}
        >
          {leadingAction}
        </span>
      ) : null}

      {hoverActions ? (
        <span
          className={cn(
            "absolute right-10 top-0 z-[2] flex h-full items-center gap-0.5 pl-8 transition-opacity motion-reduce:transition-none",
            forceHoverActionsVisible
              ? "visible pointer-events-auto opacity-100"
              : hiddenActionsClassName,
            hoverActionsClassName
          )}
        >
          {hoverActions}
        </span>
      ) : null}

      {showIndicator ? (
        <span
          className={cn(
            "pointer-events-none absolute right-3 z-[2] grid h-[22px] w-[22px] place-items-center text-primary translate-x-1 opacity-0 transition-[opacity,transform] duration-200 ease-out motion-reduce:transition-none",
            forceHoverActionsVisible
              ? "translate-x-0 opacity-100"
              : "group-hover:translate-x-0 group-hover:opacity-100 group-has-[:focus-visible]:translate-x-0 group-has-[:focus-visible]:opacity-100",
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
