import type * as React from "react";

import { cn } from "../lib/utils";

/** A data table in the list idiom: tinted 32px head, 36px rows, 13px text. Put it in a ListFrame. */
function Table({ className, ...props }: React.ComponentProps<"table">) {
  return (
    <div data-slot="table-container" className="relative w-full overflow-x-auto">
      <table data-slot="table" className={cn("w-full caption-bottom text-[13px]", className)} {...props} />
    </div>
  );
}

function TableHeader({ className, ...props }: React.ComponentProps<"thead">) {
  return <thead data-slot="table-header" className={cn("[&_tr]:border-b", className)} {...props} />;
}

function TableBody({ className, ...props }: React.ComponentProps<"tbody">) {
  return <tbody data-slot="table-body" className={cn("[&_tr:last-child]:border-0", className)} {...props} />;
}

function TableRow({ className, ...props }: React.ComponentProps<"tr">) {
  return (
    <tr
      data-slot="table-row"
      className={cn("hover:bg-muted/60 data-[state=selected]:bg-muted border-b transition-colors", className)}
      {...props}
    />
  );
}

function TableHead({ className, ...props }: React.ComponentProps<"th">) {
  return (
    <th
      data-slot="table-head"
      className={cn(
        "text-muted-foreground h-8 px-3 text-left align-middle text-xs font-medium whitespace-nowrap",
        className,
      )}
      {...props}
    />
  );
}

function TableCell({ className, ...props }: React.ComponentProps<"td">) {
  return (
    <td data-slot="table-cell" className={cn("h-9 px-3 py-1 align-middle whitespace-nowrap", className)} {...props} />
  );
}

/** A group heading inside a table body, styled like a list group header. */
function TableGroupRow({
  colSpan,
  children,
  className,
}: {
  colSpan: number;
  children: React.ReactNode;
  className?: string;
}) {
  return (
    <tr className="bg-muted/70 border-b">
      <td colSpan={colSpan} className={cn("h-8 px-3 align-middle", className)}>
        <div className="flex min-w-0 items-center gap-2">{children}</div>
      </td>
    </tr>
  );
}

export { Table, TableHeader, TableBody, TableHead, TableRow, TableCell, TableGroupRow };
