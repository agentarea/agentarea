"use client";

import type { ReactNode } from "react";
import { ArrowUpRight } from "lucide-react";
import Link from "@/components/WorkspaceLink";
import { cn } from "@/lib/utils";

export default function InfoPanelValueBox({
  children,
  className,
  mono = false,
  href,
  newTab = false,
}: {
  children: ReactNode;
  className?: string;
  mono?: boolean;
  /**
   * Makes the box a link to the value's own page: the box is lit as a whole on
   * hover, with the arrow saying it opens another page — not an underline.
   */
  href?: string;
  /** Open `href` in a new browser tab, leaving the page where it is. */
  newTab?: boolean;
}) {
  const boxClassName = cn(
    "truncate rounded-md border border-border/50 bg-muted/30 p-1.5 text-xs text-foreground",
    mono && "font-mono",
    className
  );

  if (!href) {
    return <div className={boxClassName}>{children}</div>;
  }

  return (
    <Link
      href={href}
      {...(newTab ? { target: "_blank", rel: "noopener noreferrer" } : {})}
      className={cn(
        boxClassName,
        "group/value flex items-center gap-2 transition-colors hover:bg-muted/50 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring"
      )}
    >
      <div className="min-w-0 flex-1 truncate">{children}</div>
      <ArrowUpRight
        aria-hidden
        strokeWidth={1.5}
        className="h-3.5 w-3.5 shrink-0 text-muted-foreground opacity-0 transition-opacity group-hover/value:opacity-100 group-focus-visible/value:opacity-100"
      />
    </Link>
  );
}
