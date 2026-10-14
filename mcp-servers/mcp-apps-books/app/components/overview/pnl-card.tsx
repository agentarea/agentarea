import { Chip } from "@kit/components/chip";
import { ListFrame } from "@kit/components/list";
import { InlineStatus, toStatus, type Status } from "@kit/components/notes";
import { Section } from "@kit/components/section";
import { cn } from "@kit/lib/utils";
import { Table, TableBody, TableCell, TableGroupRow, TableHead, TableHeader, TableRow } from "@kit/ui/table";
import type { Overview, PnlLine } from "@shared/schema";
import { ChevronRight } from "lucide-react";
import { useState } from "react";
import { Money } from "@/components/money";

export function PnlCard({
  overview,
  onOpenCategory,
  className,
}: {
  overview: Overview;
  onOpenCategory: (categoryId: string | null) => Promise<string | null>;
  className?: string;
}) {
  const [status, setStatus] = useState<Status>(null);
  const { pnl, book } = overview;
  const open = async (line: PnlLine) => setStatus(await toStatus(onOpenCategory(line.categoryId)));

  const section = (title: string, lines: PnlLine[], total: number, tone: "income" | "expense") => (
    <>
      <TableGroupRow colSpan={3}>
        <h3 className="text-[13px] font-medium">{title}</h3>
        <span className="text-muted-foreground tabular text-xs">{lines.length}</span>
      </TableGroupRow>
      {lines.length === 0 ? (
        <TableRow className="hover:bg-transparent">
          <TableCell colSpan={3} className="text-subtle-foreground text-xs">
            Nothing in this period.
          </TableCell>
        </TableRow>
      ) : (
        lines.map((line) => {
          const share = total > 0 ? Math.max(0, line.amount / total) : 0;
          return (
            <TableRow key={line.categoryId ?? "none"} className="group cursor-pointer" onClick={() => void open(line)}>
              <TableCell className="whitespace-normal">
                <div className="flex min-w-0 items-center gap-2.5">
                  <span
                    className="bg-muted relative hidden h-1 w-14 shrink-0 overflow-hidden rounded-full sm:block"
                    aria-hidden
                  >
                    <span
                      className={cn(
                        "absolute inset-y-0 left-0 rounded-full",
                        tone === "income" ? "bg-(--chart-income)" : "bg-muted-foreground/50",
                      )}
                      style={{ width: `${(share * 100).toFixed(1)}%` }}
                    />
                  </span>
                  <span className={cn("truncate", line.categoryId === null && "text-warning")}>{line.name}</span>
                  {line.categoryId === null && <Chip tone="warning">review</Chip>}
                </div>
              </TableCell>
              <TableCell className="text-subtle-foreground tabular hidden w-14 text-right text-xs sm:table-cell">
                {line.count}
              </TableCell>
              <TableCell className="text-right">
                <span className="inline-flex items-center gap-1">
                  <Money minor={line.amount} currency={pnl.currency} locale={book.locale} />
                  <ChevronRight className="text-subtle-foreground size-3.5 opacity-0 group-hover:opacity-100" />
                </span>
              </TableCell>
            </TableRow>
          );
        })
      )}
      <TableRow className="hover:bg-transparent">
        <TableCell className="text-muted-foreground">Total {title.toLowerCase()}</TableCell>
        <TableCell className="hidden sm:table-cell" />
        <TableCell className="pr-[30px] text-right font-medium">
          <Money minor={total} currency={pnl.currency} locale={book.locale} />
        </TableCell>
      </TableRow>
    </>
  );

  return (
    <Section
      className={className}
      title="Profit and loss"
      meta={`${overview.period.label}, cash basis`}
      actions={<InlineStatus status={status} />}
    >
      <ListFrame>
        <Table>
          <TableHeader>
            <TableRow className="hover:bg-transparent">
              <TableHead>Category</TableHead>
              <TableHead className="hidden text-right sm:table-cell">Lines</TableHead>
              <TableHead className="pr-[30px] text-right">Amount</TableHead>
            </TableRow>
          </TableHeader>
          <TableBody>
            {section("Income", pnl.income, pnl.totalIncome, "income")}
            {section("Expenses", pnl.expenses, pnl.totalExpenses, "expense")}
            <TableRow className="hover:bg-transparent">
              <TableCell className="font-semibold">Net profit</TableCell>
              <TableCell className="hidden sm:table-cell" />
              <TableCell className="pr-[30px] text-right font-semibold">
                <Money minor={pnl.net} currency={pnl.currency} locale={book.locale} />
              </TableCell>
            </TableRow>
          </TableBody>
        </Table>
      </ListFrame>
    </Section>
  );
}
