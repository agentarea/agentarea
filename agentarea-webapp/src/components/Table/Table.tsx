import { ArrowUpIcon } from "lucide-react";
import { Button } from "@/components/ui/button";
import {
  TableBody,
  TableCell,
  Table as TableComponent,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table";
import { cn } from "@/lib/utils";

export type Column<T = unknown> = {
  header: string;
  accessor: string;
  render?(value: unknown, item?: T): React.ReactNode;
  headerClassName?: string;
  cellClassName?: string;
  sortable?: boolean;
  sortableDirection?: "asc" | "desc";
};

interface TableProps<T> {
  data: T[];
  columns: Column<T>[];
  onRowClick?: (item: T) => void;
  className?: string;
}

export default function Table<T>({
  data,
  columns,
  onRowClick,
  className,
}: TableProps<T>) {
  return (
    <TableComponent className={className}>
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
        <TableRow className="pointer-events-none hover:bg-transparent">
          {columns.map((column) => (
            <TableHead
              key={column.accessor}
              className={cn(
                "h-auto py-[4px] text-[11px] font-medium uppercase text-zinc-400 first:pl-[20px] last:pr-[20px] dark:text-zinc-400",
                column.headerClassName
              )}
            >
              {column.header}
              {column.sortable && (
                <Button variant="ghost" size="icon" className="ml-2">
                  <ArrowUpIcon />
                </Button>
              )}
            </TableHead>
          ))}
        </TableRow>
      </TableHeader>
      <TableBody>
        {data.map((item) => {
          const row = item as Record<string, unknown>;
          return (
            <TableRow
              key={row.id as React.Key}
              onClick={() => onRowClick?.(item)}
              className={cn(
                "group cursor-pointer border-b border-zinc-100 transition-colors duration-200 hover:bg-primary/5 dark:border-zinc-800 dark:hover:bg-primary/10",
                row.className as string | undefined
              )}
            >
              {columns.map((column) => (
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
              ))}
            </TableRow>
          );
        })}
      </TableBody>
    </TableComponent>
  );
}
