import type { Ledger, TransactionRow } from "@shared/schema";
import { ArrowRight, ChevronDown, CircleCheck, Circle, FileText, Paperclip } from "lucide-react";
import { Fragment, useState, type ReactNode } from "react";
import { Chip } from "@kit/components/chip";
import { InlineStatus, type Status } from "@kit/components/notes";
import { Money } from "@/components/money";
import { Button } from "@kit/ui/button";
import { Table, TableBody, TableCell, TableGroupRow, TableHead, TableHeader, TableRow } from "@kit/ui/table";
import { Tooltip, TooltipContent, TooltipTrigger } from "@kit/ui/tooltip";
import { dayMonth } from "@/lib/format";
import { cn } from "@kit/lib/utils";
import { CategorySelect } from "./category-select";

const PAGE = 150;

export function LedgerTable({
  ledger,
  selected,
  onSelect,
  rowStatus,
  onCategorize,
  onReconcile,
  onOpenInvoice,
  addRow,
}: {
  ledger: Ledger;
  selected: Set<string>;
  onSelect: (ids: string[], on: boolean) => void;
  rowStatus: Record<string, Status>;
  onCategorize: (row: TransactionRow, categoryId: string) => void;
  onReconcile: (row: TransactionRow) => void;
  onOpenInvoice: (number: string) => void;
  addRow: ReactNode;
}) {
  const [shown, setShown] = useState(PAGE);
  const rows = ledger.rows.slice(0, shown);
  const allSelected = rows.length > 0 && rows.every((r) => selected.has(r.id));
  const locale = ledger.book.locale;

  return (
    <>
      <Table>
        <TableHeader>
          <TableRow className="hover:bg-transparent">
            <TableHead className="w-9 pl-3">
              <input
                type="checkbox"
                role="checkbox"
                className="accent-foreground size-3.5 cursor-pointer align-middle"
                checked={allSelected}
                onChange={(e) =>
                  onSelect(
                    rows.map((r) => r.id),
                    e.target.checked,
                  )
                }
                aria-label="Select all shown"
              />
            </TableHead>
            <TableHead>Date</TableHead>
            <TableHead className="hidden md:table-cell">Account</TableHead>
            <TableHead className="hidden md:table-cell">Counterparty</TableHead>
            <TableHead>Description</TableHead>
            <TableHead>Category</TableHead>
            <TableHead className="text-right">Amount</TableHead>
            <TableHead className="w-10 pr-3 text-right">
              <span className="sr-only">Reconciled</span>
            </TableHead>
          </TableRow>
        </TableHeader>
        <TableBody>
          {addRow}
          {rows.length === 0 ? (
            <TableRow className="hover:bg-transparent">
              <TableCell colSpan={8} className="text-muted-foreground py-12 text-center text-sm">
                No transactions match these filters.
              </TableCell>
            </TableRow>
          ) : (
            rows.map((row, index) => (
              <Fragment key={row.id}>
                {(index === 0 || rows[index - 1].date.slice(0, 7) !== row.date.slice(0, 7)) && (
                  <MonthRow
                    month={row.date.slice(0, 7)}
                    rows={ledger.rows}
                    locale={locale}
                    currency={ledger.baseCurrency}
                  />
                )}
                <Row
                  row={row}
                  ledger={ledger}
                  locale={locale}
                  selected={selected.has(row.id)}
                  status={rowStatus[row.id] ?? null}
                  onSelect={(on) => onSelect([row.id], on)}
                  onCategorize={(categoryId) => onCategorize(row, categoryId)}
                  onReconcile={() => onReconcile(row)}
                  onOpenInvoice={onOpenInvoice}
                />
              </Fragment>
            ))
          )}
        </TableBody>
      </Table>
      {ledger.rows.length > shown && (
        <div className="border-t p-1.5">
          <Button
            variant="ghost"
            size="sm"
            className="text-muted-foreground w-full"
            onClick={() => setShown((n) => n + PAGE)}
          >
            <ChevronDown />
            Show {Math.min(PAGE, ledger.rows.length - shown)} more of {ledger.rows.length - shown}
          </Button>
        </div>
      )}
      {ledger.total > ledger.rows.length && (
        <p className="text-subtle-foreground border-t px-4 py-2 text-xs">
          {ledger.total - ledger.rows.length} older transactions match too; narrow the dates to see them.
        </p>
      )}
    </>
  );
}

const MONTHS = [
  "January",
  "February",
  "March",
  "April",
  "May",
  "June",
  "July",
  "August",
  "September",
  "October",
  "November",
  "December",
];

/** The month a run of rows belongs to, with its count and net (transfers excluded). */
function MonthRow({
  month,
  rows,
  locale,
  currency,
}: {
  month: string;
  rows: TransactionRow[];
  locale: string;
  currency: string;
}) {
  const inMonth = rows.filter((r) => r.date.startsWith(month));
  const net = inMonth.reduce(
    (sum, r) => sum + (r.direction === "in" ? r.baseAmount : r.direction === "out" ? -r.baseAmount : 0),
    0,
  );
  return (
    <TableGroupRow colSpan={8}>
      <h2 className="text-[13px] font-medium">
        {MONTHS[Number(month.slice(5, 7)) - 1]} {month.slice(0, 4)}
      </h2>
      <span className="text-muted-foreground tabular text-xs">{inMonth.length}</span>
      <span className="text-subtle-foreground ml-auto text-xs">
        net <Money minor={net} currency={currency} locale={locale} className="text-muted-foreground" />
      </span>
    </TableGroupRow>
  );
}

function Row({
  row,
  ledger,
  locale,
  selected,
  status,
  onSelect,
  onCategorize,
  onReconcile,
  onOpenInvoice,
}: {
  row: TransactionRow;
  ledger: Ledger;
  locale: string;
  selected: boolean;
  status: Status;
  onSelect: (on: boolean) => void;
  onCategorize: (categoryId: string) => void;
  onReconcile: () => void;
  onOpenInvoice: (number: string) => void;
}) {
  const transfer = row.direction === "transfer";
  const review = !transfer && row.category === null;
  return (
    <TableRow data-state={selected ? "selected" : undefined} className={cn(review && "bg-warning-surface/30")}>
      <TableCell className="pl-3">
        <input
          type="checkbox"
          role="checkbox"
          className="accent-foreground size-3.5 cursor-pointer align-middle"
          checked={selected}
          onChange={(e) => onSelect(e.target.checked)}
          aria-label={`Select ${row.id}`}
        />
      </TableCell>
      <TableCell className="tabular text-muted-foreground">{dayMonth(row.date, ledger.today)}</TableCell>
      <TableCell className="hidden md:table-cell">
        {transfer ? (
          <span className="flex items-center gap-1">
            {row.account.name}
            <ArrowRight className="text-subtle-foreground size-3" />
            {row.transferAccount?.name}
          </span>
        ) : (
          <span>{row.account.name}</span>
        )}
      </TableCell>
      <TableCell className="hidden max-w-[180px] md:table-cell">
        <span className={cn("block truncate", !row.counterparty && "text-subtle-foreground")}>
          {row.counterparty?.name ?? (transfer ? "Own accounts" : "—")}
        </span>
      </TableCell>
      <TableCell className="max-w-[180px] sm:max-w-[300px]">
        <div className="flex min-w-0 items-center gap-1.5">
          <span
            className="truncate"
            title={
              row.bankMemo && row.bankMemo !== row.description
                ? `${row.description}\nBank: ${row.bankMemo}`
                : row.description
            }
          >
            {row.description}
          </span>
          {row.invoice && (
            <button type="button" className="cursor-pointer" onClick={() => onOpenInvoice(row.invoice!.number)}>
              <Chip tone="info" className="hover:border-info/70 font-mono">
                <FileText />
                {row.invoice.number}
              </Chip>
            </button>
          )}
          {row.attachments.length > 0 && (
            <Tooltip>
              <TooltipTrigger asChild>
                <span className="text-subtle-foreground inline-flex items-center gap-0.5 text-[11px]">
                  <Paperclip className="size-3" />
                  {row.attachments.length}
                </span>
              </TooltipTrigger>
              <TooltipContent>{row.attachments.join(", ")}</TooltipContent>
            </Tooltip>
          )}
        </div>
        <span className="text-subtle-foreground block truncate text-[11px] md:hidden">
          {[
            row.counterparty?.name ?? (transfer ? "Own accounts" : null),
            transfer ? `${row.account.name} → ${row.transferAccount?.name}` : row.account.name,
          ]
            .filter(Boolean)
            .join(" · ")}
        </span>
        {status && <InlineStatus status={status} className="mt-0.5" />}
      </TableCell>
      <TableCell>
        {transfer ? (
          <span className="text-subtle-foreground text-xs">Transfer</span>
        ) : (
          <CategorySelect
            ledger={ledger}
            value={row.category?.id ?? ""}
            onChange={onCategorize}
            disabled={status?.kind === "busy"}
            aria-label={`Category for ${row.id}`}
            className={cn("w-[132px] sm:w-[150px]", review && "[&_select]:text-warning")}
          />
        )}
      </TableCell>
      <TableCell className="text-right">
        <Money
          minor={row.amount}
          currency={row.currency}
          locale={locale}
          direction={row.direction}
          className="font-medium"
        />
        {row.currency !== ledger.baseCurrency && (
          <Money
            minor={row.baseAmount}
            currency={ledger.baseCurrency}
            locale={locale}
            className="text-subtle-foreground block text-[11px]"
          />
        )}
      </TableCell>
      <TableCell className="pr-3 text-right">
        <Tooltip>
          <TooltipTrigger asChild>
            <Button
              variant="ghost"
              size="xs"
              onClick={onReconcile}
              aria-pressed={row.reconciled}
              aria-label={row.reconciled ? "Reconciled; click to undo" : "Mark reconciled"}
              className={row.reconciled ? "text-success" : "text-subtle-foreground"}
            >
              {row.reconciled ? <CircleCheck /> : <Circle />}
            </Button>
          </TooltipTrigger>
          <TooltipContent side="left">
            {row.reconciled ? "Reconciled with the bank" : "Not reconciled yet"}
          </TooltipContent>
        </Tooltip>
      </TableCell>
    </TableRow>
  );
}
