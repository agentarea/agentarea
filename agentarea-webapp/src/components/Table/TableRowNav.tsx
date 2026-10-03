"use client";

import type React from "react";
import { useWorkspaceRouter } from "@/hooks/useWorkspaceNavigation";
import { TableRow } from "@/components/ui/table";

/**
 * A table row that navigates when clicked.
 *
 * The destination crosses the server/client boundary as a string, which is the
 * whole point: an `onClick` closure cannot, so rows rendered from a server
 * component used to arrive inert -- React drops the handler and the row looks
 * clickable while doing nothing. Routing here also keeps the table on the
 * client router, matching the `<Link>` the grid view uses for the same item,
 * rather than reloading the document.
 */
export function TableRowNav({
  href,
  className,
  children,
  hasNativeLink = false,
  ...props
}: {
  href: string;
  className?: string;
  children: React.ReactNode;
  /** Leave keyboard activation to an anchor rendered inside the row. */
  hasNativeLink?: boolean;
} & React.HTMLAttributes<HTMLTableRowElement>) {
  const router = useWorkspaceRouter();

  return (
    <TableRow
      role={hasNativeLink ? undefined : "link"}
      tabIndex={hasNativeLink ? undefined : 0}
      onClick={(event) => {
        if (
          hasNativeLink &&
          event.target instanceof Element &&
          event.target.closest("a")
        ) {
          return;
        }
        router.push(href);
      }}
      onKeyDown={
        hasNativeLink
          ? undefined
          : (event) => {
              if (event.key === "Enter" || event.key === " ") {
                event.preventDefault();
                router.push(href);
              }
            }
      }
      className={className}
      {...props}
    >
      {children}
    </TableRow>
  );
}

export default TableRowNav;
