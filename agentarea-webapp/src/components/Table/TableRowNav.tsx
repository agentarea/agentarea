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
  ...props
}: {
  href: string;
  className?: string;
  children: React.ReactNode;
} & React.HTMLAttributes<HTMLTableRowElement>) {
  const router = useWorkspaceRouter();

  return (
    <TableRow
      role="link"
      tabIndex={0}
      onClick={() => router.push(href)}
      onKeyDown={(event) => {
        if (event.key === "Enter" || event.key === " ") {
          event.preventDefault();
          router.push(href);
        }
      }}
      className={className}
      {...props}
    >
      {children}
    </TableRow>
  );
}

export default TableRowNav;
