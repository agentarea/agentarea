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

export default function Table({data, columns}: {data: any[], columns: Column[]}) {
    return (
        <div className="relative flex flex-col h-full">
            <div className="sticky top-0 z-10 w-full">
                <TableComponent>
                    <TableHeader>
                        <TableRow className="bg-zinc-100 dark:bg-zinc-800 hover:bg-zinc-100 dark:hover:bg-zinc-800 border-zinc-200 dark:border-zinc-700">
                            {columns.map((column) => (
                                <TableHead key={column.accessor} className={cn("text-[11px] text-zinc-400 dark:text-zinc-400 uppercase font-medium first:pl-[20px] last:pr-[20px]", "last:rounded-tr-lg first:rounded-tl-lg", column.headerClassName)}>
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
                </TableComponent>
            </div>
            <div className="overflow-y-auto flex-1">
                <TableComponent>
                    <TableBody>
                        {data.map((item) => (
                            <TableRow key={item.id} className="hover:bg-accent/10 dark:hover:bg-white/10 cursor-pointer transition-all duration-300 py-[18px] border-zinc-100 dark:border-zinc-700">
                                {columns.map((column) => (
                                    <TableCell key={item.id + "-" + column.accessor}
                                        className={cn("py-[18px] first:pl-[20px] last:pr-[20px]", column.cellClassName)}
                                    >
                                        {column.render ? column.render(item[column.accessor], item) : item[column.accessor]}
                                    </TableCell>
                                ))}
                            </TableRow>
                        ))}
                    </TableBody>
                </TableComponent>
            </div>
        </div>
    )
}