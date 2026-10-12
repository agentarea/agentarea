import { Chip } from "@kit/components/chip";
import { LinkList, LinkRow } from "@kit/components/list";
import { InlineStatus, toStatus, type Status } from "@kit/components/notes";
import { Section } from "@kit/components/section";
import { cn } from "@kit/lib/utils";
import type { AgingBucket } from "@shared/books";
import type { Overview } from "@shared/schema";
import { useState } from "react";
import { Money } from "@/components/money";
import { dayMonth } from "@/lib/format";

const BUCKETS: { key: AgingBucket; label: string; bar: string }[] = [
  { key: "current", label: "Not due", bar: "bg-(--chart-income)" },
  { key: "d1_30", label: "1–30 days", bar: "bg-warning/45" },
  { key: "d31_60", label: "31–60 days", bar: "bg-warning/80" },
  { key: "d60_plus", label: "60+ days", bar: "bg-danger/80" },
];

export function ReceivablesCard({
  overview,
  onOpenInvoice,
  className,
}: {
  overview: Overview;
  onOpenInvoice: (number: string) => Promise<string | null>;
  className?: string;
}) {
  const [status, setStatus] = useState<Status>(null);
  const { aging, book, today } = overview;

  return (
    <Section
      className={className}
      title="Receivables"
      meta={`by days past due, ${dayMonth(today)}`}
      actions={<InlineStatus status={status} />}
    >
      <LinkList>
        <li className="border-b px-3 py-3">
          <div className="bg-muted flex h-1.5 w-full gap-px overflow-hidden rounded-full" aria-hidden>
            {aging.total > 0 &&
              BUCKETS.map((b) => (
                <div key={b.key} className={b.bar} style={{ width: `${(aging[b.key] / aging.total) * 100}%` }} />
              ))}
          </div>
          <dl className="mt-2.5 grid grid-cols-2 gap-x-4 gap-y-2 sm:grid-cols-4">
            {BUCKETS.map((b) => (
              <div key={b.key} className="min-w-0">
                <dt className="text-muted-foreground flex items-center gap-1.5 text-[11px]">
                  <span className={cn("size-1.5 rounded-full", b.bar)} />
                  {b.label}
                </dt>
                <dd className="mt-0.5 text-[13px] font-medium">
                  <Money minor={aging[b.key]} currency={aging.currency} locale={book.locale} />
                </dd>
              </div>
            ))}
          </dl>
        </li>
        <li className="bg-muted/70 flex h-8 items-center gap-2 border-b px-3">
          <h3 className="text-[13px] font-medium">Overdue</h3>
          <span className="text-muted-foreground tabular text-xs">{overview.overdueInvoices.length}</span>
        </li>
        {overview.overdueInvoices.length === 0 ? (
          <li className="text-subtle-foreground px-3 py-4 text-center text-xs">Nothing is past due.</li>
        ) : (
          overview.overdueInvoices.map((invoice) => (
            <LinkRow
              key={invoice.id}
              className="h-auto py-2"
              onClick={async () => setStatus(await toStatus(onOpenInvoice(invoice.number)))}
            >
              <span className="text-muted-foreground hidden w-[72px] shrink-0 font-mono text-[11px] sm:inline">
                {invoice.number}
              </span>
              <span className="min-w-0 flex-1">
                <span className="block truncate">{invoice.client.name}</span>
                <span className="text-subtle-foreground block truncate text-[11px]">
                  <span className="font-mono sm:hidden">{invoice.number} · </span>
                  due {dayMonth(invoice.dueDate, today)}
                  {invoice.amountPaid > 0 ? " · part paid" : ""}
                </span>
              </span>
              <Chip tone={invoice.daysOverdue > 60 ? "danger" : "warning"} className="tabular">
                {invoice.daysOverdue}d late
              </Chip>
              <Money
                minor={invoice.balanceDue}
                currency={invoice.currency}
                locale={book.locale}
                className="shrink-0 text-right font-medium sm:w-[104px]"
              />
            </LinkRow>
          ))
        )}
      </LinkList>
    </Section>
  );
}
