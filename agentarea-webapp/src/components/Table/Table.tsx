import { Fragment } from "react";
import { ArrowDownIcon, ArrowUpDownIcon, ArrowUpIcon } from "lucide-react";
import Link from "@/components/WorkspaceLink";
import {
  Collapsible,
  CollapsibleContent,
} from "@/components/ui/collapsible";
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
  /** Marks this cell as the native link for a row with `rowHref`. */
  rowLink?: boolean;
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
  /**
   * Opt-in detail row under a row, spanning every column. The caller owns
   * which rows are open (toggle it from `onRowClick`), so the table stays
   * usable from a server component.
   */
  isExpanded?: (item: T) => boolean;
  renderExpanded?: (item: T) => React.ReactNode;
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
  isExpanded,
  renderExpanded,
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
                        "inline-flex min-h-11 min-w-11 items-center justify-center gap-1 uppercase hover:text-foreground focus-visible:outline focus-visible:outline-2 focus-visible:outline-ring md:min-h-6 md:min-w-6",
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
          const hasRowLink = Boolean(href && columns.some((column) => column.rowLink));
          const expanded = Boolean(renderExpanded && isExpanded?.(item));
          const rowClassName = cn(
            "group border-b border-zinc-100 transition-colors duration-200 dark:border-zinc-800",
            (href || onRowClick) &&
              "cursor-pointer hover:bg-primary/5 dark:hover:bg-primary/10",
            // An open row and its details read as one block: no rule between
            // them, and the details' background carried up into the row.
            expanded && "border-b-transparent bg-muted/20",
            row.className as string | undefined,
            extraClassName
          );
          const cells = columns.map((column) => {
            const content = column.render
              ? column.render(row[column.accessor], item)
              : (row[column.accessor] as React.ReactNode);
            return (
              <TableCell
                key={String(row.id) + "-" + column.accessor}
                className={cn(
                  "py-[10px] first:pl-[20px] last:pr-[20px]",
                  column.cellClassName
                )}
              >
                {href && column.rowLink ? (
                  <Link
                    href={href}
                    className="block rounded-sm focus-visible:outline focus-visible:outline-2 focus-visible:outline-ring"
                  >
                    {content}
                  </Link>
                ) : (
                  content
                )}
              </TableCell>
            );
          });

          return href ? (
            <TableRowNav
              key={row.id as React.Key}
              href={href}
              hasNativeLink={hasRowLink}
              {...extraRowProps}
              className={rowClassName}
            >
              {cells}
            </TableRowNav>
          ) : (
            <Fragment key={row.id as React.Key}>
              <TableRow
                // Built only when there is something to call. A closure handed
                // over unconditionally is one a server component cannot pass at
                // all, which is what used to make these rows dead on arrival.
                onClick={onRowClick ? () => onRowClick(item) : undefined}
                aria-expanded={renderExpanded ? expanded : undefined}
                {...extraRowProps}
                className={rowClassName}
              >
                {cells}
              </TableRow>
              {renderExpanded && (
                // Always in the DOM, zero-height while closed: the collapsible
                // animates the open and the close (Radix keeps the content
                // mounted until the close finishes) and drops it afterwards.
                <TableRow className="border-0 hover:bg-transparent">
                  <TableCell colSpan={columns.length} className="p-0">
                    <Collapsible open={expanded}>
                      <CollapsibleContent className="aa-collapsible">
                        <div className="border-b border-zinc-100 bg-muted/20 px-[20px] py-3 dark:border-zinc-800">
                          {renderExpanded(item)}
                        </div>
                      </CollapsibleContent>
                    </Collapsible>
                  </TableCell>
                </TableRow>
              )}
            </Fragment>
          );
        })}
      </TableBody>
    </TableComponent>
  );
}
