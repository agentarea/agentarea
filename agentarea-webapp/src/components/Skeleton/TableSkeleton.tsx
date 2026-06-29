import { Skeleton } from "@/components/ui/skeleton";
import {
  TableBody,
  TableCell,
  Table as TableComponent,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table";
import { cn } from "@/lib/utils";

/**
 * A column descriptor for the table skeleton. It mirrors the meaningful bits of
 * the real `Table` column (header label + cell width) so the skeleton lines up
 * with the actual table once data arrives. `render`/`accessor` are irrelevant
 * here — only layout matters.
 */
export type SkeletonColumn = {
  /** Real, static header label (no data needed) — keeps the header faithful. */
  header?: React.ReactNode;
  headerClassName?: string;
  cellClassName?: string;
  /** Width/shape of the shimmering bar inside each body cell. */
  barClassName?: string;
};

interface TableSkeletonProps {
  columns: SkeletonColumn[];
  rows?: number;
}

// Same diagonal hatch the real `Table` header uses, so the two are visually
// identical while loading.
const HEADER_HATCH = `repeating-linear-gradient(
  -45deg,
  color-mix(in srgb, currentColor 4%, transparent),
  color-mix(in srgb, currentColor 4%, transparent) 1px,
  transparent 1px,
  transparent 10px
)`;

/**
 * Loading placeholder for the shared `Table` component. Renders the real
 * (static) header row plus `rows` shimmering body rows that match the real
 * table's padding/borders.
 */
export default function TableSkeleton({ columns, rows = 8 }: TableSkeletonProps) {
  return (
    <TableComponent>
      <TableHeader
        className="relative"
        style={{ backgroundImage: HEADER_HATCH }}
      >
        <TableRow className="pointer-events-none hover:bg-transparent">
          {columns.map((column, index) => (
            <TableHead
              key={index}
              className={cn(
                "h-auto py-[4px] text-[11px] font-medium uppercase text-zinc-400 first:pl-[20px] last:pr-[20px] dark:text-zinc-400",
                column.headerClassName
              )}
            >
              {column.header}
            </TableHead>
          ))}
        </TableRow>
      </TableHeader>
      <TableBody>
        {Array.from({ length: rows }).map((_, rowIndex) => (
          <TableRow
            key={rowIndex}
            className="border-b border-zinc-100 hover:bg-transparent dark:border-zinc-800"
          >
            {columns.map((column, colIndex) => (
              <TableCell
                key={colIndex}
                className={cn(
                  "py-[10px] first:pl-[20px] last:pr-[20px]",
                  column.cellClassName
                )}
              >
                <Skeleton className={cn("h-4 w-24", column.barClassName)} />
              </TableCell>
            ))}
          </TableRow>
        ))}
      </TableBody>
    </TableComponent>
  );
}
