"use client";

import type { ReactNode } from "react";
import { ArrowUpRight } from "lucide-react";
import Link from "@/components/WorkspaceLink";
import { cn } from "@/lib/utils";

/**
 * One related thing in an info panel: tile, name, a muted line under it. A row
 * that leads somewhere is lit as a whole on hover, as list rows inside a panel
 * are, with the arrow saying it opens another page — not an underlined name.
 * `trailing` sits outside the link (e.g. a remove button); `children` go under
 * the row (e.g. a tool list).
 */
export default function InfoPanelRow({
  avatar,
  name,
  badge,
  sub,
  href,
  newTab = false,
  title,
  trailing,
  children,
}: {
  avatar: ReactNode;
  name: ReactNode;
  /** Next to the name, e.g. "You". */
  badge?: ReactNode;
  sub?: ReactNode;
  href?: string;
  /** Open `href` in a new browser tab, leaving the page where it is. */
  newTab?: boolean;
  title?: string;
  trailing?: ReactNode;
  children?: ReactNode;
}) {
  const body = (
    <>
      {avatar}
      <span className="min-w-0 flex-1">
        <span className="flex min-w-0 items-center gap-1.5">
          <span className="truncate text-[12px] font-medium text-foreground">
            {name}
          </span>
          {badge}
        </span>
        {sub && (
          <span className="block truncate text-[10px] text-muted-foreground">
            {sub}
          </span>
        )}
      </span>
    </>
  );
  const rowClassName =
    "-mx-1.5 flex min-w-0 flex-1 items-center gap-2 rounded-md px-1.5 py-1";

  const row = href ? (
    <Link
      href={href}
      title={title}
      {...(newTab ? { target: "_blank", rel: "noopener noreferrer" } : {})}
      className={cn(
        rowClassName,
        "group/row transition-colors hover:bg-muted/40 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring"
      )}
    >
      {body}
      <ArrowUpRight
        aria-hidden
        strokeWidth={1.5}
        className="h-3.5 w-3.5 shrink-0 text-muted-foreground opacity-0 transition-opacity group-hover/row:opacity-100 group-focus-visible/row:opacity-100"
      />
    </Link>
  ) : (
    <div className={rowClassName} title={title}>
      {body}
    </div>
  );

  if (!trailing && !children) return row;
  return (
    <div>
      <div className="flex items-center gap-1">
        {row}
        {trailing}
      </div>
      {children}
    </div>
  );
}
