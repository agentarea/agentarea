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

type Column = {
  header: string;
  accessor: string;
  render?: (value: any, item?: any) => React.ReactNode;
  headerClassName?: string;
  cellClassName?: string;
  sortable?: boolean;
  sortableDirection?: "asc" | "desc";
};

interface TableProps {
  data: any[];
  columns: Column[];
  onRowClick?: (item: any) => void;
}

export default function Table({ data, columns, onRowClick }: TableProps) {
  return (
    <TableComponent>
      <TableHeader>
        <TableRow className="pointer-events-none">
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
                  <ArrowUpIcon className="h-4 w-4" />
                </Button>
              )}
            </TableHead>
          ))}
        </TableRow>
      </TableHeader>
      <TableBody>
        {data.map((item) => (
          <TableRow
            key={item.id}
            onClick={() => onRowClick?.(item)}
            className={cn(
              "group cursor-pointer border-zinc-100 py-[18px] transition-all duration-300 hover:bg-primary/10 dark:border-zinc-700 dark:hover:bg-white/10",
              item.className
            )}
          >
            {columns.map((column) => (
              <TableCell
                key={item.id + "-" + column.accessor}
                className={cn(
                  "py-[10px] first:pl-[20px] last:pr-[20px]",
                  column.cellClassName
                )}
              >
                {column.render
                  ? column.render(item[column.accessor], item)
                  : item[column.accessor]}
              </TableCell>
            ))}
          </TableRow>
        ))}
      </TableBody>
    </TableComponent>
  );
}
