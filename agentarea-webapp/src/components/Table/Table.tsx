import { ArrowDownIcon, ArrowUpDownIcon, ArrowUpIcon } from "lucide-react";
import {
  TableBody,
  TableCell,
  Table as TableComponent,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table";
import { cn } from "@/lib/utils";
import { TableRowNav } from "./TableRowNav";

export type Column<T = unknown> = {
  header: string;
  accessor: string;
  render?(value: unknown, item?: T): React.ReactNode;
  headerClassName?: string;
  cellClassName?: string;
  /** Makes the header a sort toggle; takes effect only with `onSortChange`. */
  sortable?: boolean;
};

export type TableSort = { accessor: string; direction: "asc" | "desc" };

interface TableProps<T> {
  data: T[];
  columns: Column<T>[];
  onRowClick?: (item: T) => void;
  className?: string;
  /** Extra attributes for each row, e.g. to make it a drag source or drop target. */
  rowProps?: (item: T) => React.HTMLAttributes<HTMLElement>;
  /**
   * Where a row leads. Resolved during render, so only the string crosses into
   * the client — which is what makes a clickable row work in a table rendered
   * from a server component, where `onRowClick` cannot be handed over at all.
   * Prefer this over `onRowClick` whenever the click is plain navigation.
   */
  rowHref?: (item: T) => string;
  /** Drop the column header row — for stacked tables that share one header. */
  hideHeader?: boolean;
  /** The order `data` is already in. The table never reorders rows itself;
   * the caller sorts, since only it knows how its values compare. */
  sort?: TableSort;
  onSortChange?: (sort: TableSort) => void;
}

export default function Table<T>({
  data,
  columns,
  onRowClick,
  className,
  rowProps,
  rowHref,
  hideHeader = false,
  sort,
  onSortChange,
}: TableProps<T>) {
  return (
    <TableComponent className={className}>
      {!hideHeader && (
        <TableHeader
          className="relative"
          style={{
            backgroundImage: `repeating-linear-gradient(
            -45deg,
            color-mix(in srgb, currentColor 4%, transparent),
            color-mix(in srgb, currentColor 4%, transparent) 1px,
            transparent 1px,
            transparent 10px
          )`,
          }}
        >
          <TableRow className="hover:bg-transparent">
            {columns.map((column) => {
              const sortable = column.sortable && onSortChange;
              const active = sort?.accessor === column.accessor;
              const SortIcon = !active
                ? ArrowUpDownIcon
                : sort.direction === "asc"
                  ? ArrowUpIcon
                  : ArrowDownIcon;
              return (
                <TableHead
                  key={column.accessor}
                  aria-sort={
                    !sortable
                      ? undefined
                      : !active
                        ? "none"
                        : sort.direction === "asc"
                          ? "ascending"
                          : "descending"
                  }
                  className={cn(
                    "h-auto py-[4px] text-[11px] font-medium uppercase text-zinc-400 first:pl-[20px] last:pr-[20px] dark:text-zinc-400",
                    column.headerClassName
                  )}
                >
                  {sortable ? (
                    <button
                      type="button"
                      onClick={() =>
                        onSortChange({
                          accessor: column.accessor,
                          direction:
                            active && sort.direction === "asc" ? "desc" : "asc",
                        })
                      }
                      className={cn(
                        "inline-flex items-center gap-1 uppercase hover:text-foreground focus-visible:outline focus-visible:outline-2 focus-visible:outline-ring",
                        active && "text-foreground"
                      )}
                    >
                      {column.header}
                      <SortIcon
                        className={cn("h-3 w-3", !active && "opacity-40")}
                      />
                    </button>
                  ) : (
                    column.header
                  )}
                </TableHead>
              );
            })}
          </TableRow>
        </TableHeader>
      )}
      <TableBody>
        {data.map((item) => {
          const row = item as Record<string, unknown>;
          const { className: extraClassName, ...extraRowProps } =
            rowProps?.(item) ?? {};
          const href = rowHref?.(item);
          const rowClassName = cn(
            "group border-b border-zinc-100 transition-colors duration-200 dark:border-zinc-800",
            // Only a table that actually handles the click should look
            // clickable; without this every row invites one that does nothing.
            (href || onRowClick) &&
              "cursor-pointer hover:bg-primary/5 dark:hover:bg-primary/10",
            row.className as string | undefined,
            extraClassName
          );
          const cells = columns.map((column) => (
            <TableCell
              key={String(row.id) + "-" + column.accessor}
              className={cn(
                "py-[10px] first:pl-[20px] last:pr-[20px]",
                column.cellClassName
              )}
            >
              {column.render
                ? column.render(row[column.accessor], item)
                : (row[column.accessor] as React.ReactNode)}
            </TableCell>
          ));

          return href ? (
            <TableRowNav
              key={row.id as React.Key}
              href={href}
              {...extraRowProps}
              className={rowClassName}
            >
              {cells}
            </TableRowNav>
          ) : (
            <TableRow
              key={row.id as React.Key}
              // Built only when there is something to call. A closure handed
              // over unconditionally is one a server component cannot pass at
              // all, which is what used to make these rows dead on arrival.
              onClick={onRowClick ? () => onRowClick(item) : undefined}
              {...extraRowProps}
              className={rowClassName}
            >
              {cells}
            </TableRow>
          );
        })}
      </TableBody>
    </TableComponent>
  );
}
