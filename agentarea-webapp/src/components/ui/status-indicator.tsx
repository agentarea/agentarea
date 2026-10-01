import * as React from "react";
import {
  Circle,
  CircleAlert,
  CircleCheck,
  CircleDashed,
  CircleDot,
  CircleMinus,
  CirclePause,
  CircleSlash,
  CircleX,
  Clock,
  LoaderCircle,
  type LucideIcon,
} from "lucide-react";
import type { StatusIndicatorSize, StatusKind } from "@/lib/status";
import { cn } from "@/lib/utils";

/** One glyph and one colour per kind — the whole status vocabulary. Colours
 * track `STATUS_KIND_COLOR` in `@/lib/status`. */
const KIND_STYLES = {
  draft: { Icon: CircleDashed, color: "text-muted-foreground" },
  queued: { Icon: Circle, color: "text-muted-foreground" },
  scheduled: { Icon: Clock, color: "text-muted-foreground" },
  running: {
    Icon: LoaderCircle,
    color:
      "text-[color:var(--status-info)] motion-safe:animate-spin [animation-duration:2.4s]",
  },
  attention: { Icon: CircleAlert, color: "text-[color:var(--status-attention)]" },
  paused: { Icon: CirclePause, color: "text-muted-foreground" },
  active: { Icon: CircleDot, color: "text-[color:var(--status-success)]" },
  off: { Icon: CircleMinus, color: "text-muted-foreground" },
  done: { Icon: CircleCheck, color: "text-primary" },
  failed: { Icon: CircleX, color: "text-[color:var(--status-danger)]" },
  cancelled: { Icon: CircleSlash, color: "text-muted-foreground" },
} satisfies Record<StatusKind, { Icon: LucideIcon; color: string }>;

const SIZE_STYLES = {
  default: { root: "gap-1.5 text-[12.5px]", icon: "h-3.5 w-3.5" },
  sm: { root: "gap-1 text-xs", icon: "h-3 w-3" },
} satisfies Record<StatusIndicatorSize, { root: string; icon: string }>;

export type { StatusIndicatorSize, StatusKind } from "@/lib/status";

export interface StatusIndicatorProps
  extends React.HTMLAttributes<HTMLSpanElement> {
  kind: StatusKind;
  size?: StatusIndicatorSize;
  iconClassName?: string;
}

/**
 * The only way a status reaches the screen: a coloured glyph and a neutral
 * label. Without children it is the glyph alone — give it an `aria-label`.
 */
export function StatusIndicator({
  kind,
  size = "default",
  className,
  iconClassName,
  children,
  ...props
}: StatusIndicatorProps) {
  const { Icon, color } = KIND_STYLES[kind];
  const sizeStyles = SIZE_STYLES[size];

  return (
    <span
      className={cn(
        "inline-flex w-fit items-center font-normal",
        sizeStyles.root,
        className
      )}
      {...props}
    >
      <Icon
        aria-hidden="true"
        strokeWidth={2.25}
        className={cn("shrink-0", sizeStyles.icon, color, iconClassName)}
      />
      {children ? <span>{children}</span> : null}
    </span>
  );
}
