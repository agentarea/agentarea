import { Table as TableComponent, TableHeader, TableRow, TableHead, TableCell, TableBody } from "@/components/ui/table";
import { cn } from "@/lib/utils";
import { Button } from "@/components/ui/button";
import { ArrowUpIcon } from "lucide-react";

type Column = {
    header: string;
    accessor: string;
    render?: (value: any, item?: any) => React.ReactNode;
    headerClassName?: string;
    cellClassName?: string;
    sortable?: boolean;
    sortableDirection?: "asc" | "desc";
}

interface TableProps {
    data: any[];
    columns: Column[];
    onRowClick?: (item: any) => void;
}

export default function Table({data, columns, onRowClick}: TableProps) {
    return (
        <TableComponent>
            <TableHeader>
                <TableRow className="pointer-events-none">
                    {columns.map((column) => (
                        <TableHead key={column.accessor} className={cn("h-auto py-[4px] text-[11px] text-zinc-400 dark:text-zinc-400 uppercase font-medium first:pl-[20px] last:pr-[20px]", column.headerClassName)}>
                            {column.header}
                            {column.sortable && (
                                <Button variant="ghost" size="icon" className="ml-2">
                                    <ArrowUpIcon className="w-4 h-4" />
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
                        className={cn("hover:bg-primary/10 dark:hover:bg-white/10 cursor-pointer transition-all duration-300 py-[18px] border-zinc-100 dark:border-zinc-700 group", item.className)}
                    >
                        {columns.map((column) => (
                            <TableCell key={item.id + "-" + column.accessor}
                                className={cn("py-[10px] first:pl-[20px] last:pr-[20px]", column.cellClassName)}
                            >
                                {column.render ? column.render(item[column.accessor], item) : item[column.accessor]}
                            </TableCell>
                        ))}
                    </TableRow>
                ))}
            </TableBody>
        </TableComponent>
    )
}