import { Section } from "@kit/components/section";
import { Strong, Timeline, TimelineEvent, When } from "@kit/components/timeline";
import type { InvoiceView } from "@shared/schema";
import { Ban, CircleCheck, FilePlus, Send } from "lucide-react";
import type { ReactNode } from "react";
import { Money } from "@/components/money";
import { shortDate } from "@/lib/format";

const glyph = (icon: ReactNode, className: string) => (
  <span className={`mt-0.5 flex size-4 shrink-0 items-center justify-center [&>svg]:size-3.5 ${className}`}>
    {icon}
  </span>
);

/** What happened to the invoice: issued, sent, each payment, voided. */
export function InvoiceHistory({ view }: { view: InvoiceView }) {
  const { invoice, payments, book } = view;
  const at = (date: string) => <When at={date} label={shortDate(date.slice(0, 10))} />;
  const items: { at: string; node: ReactNode }[] = [
    {
      at: invoice.issueDate,
      node: (
        <TimelineEvent key="issued" icon={glyph(<FilePlus />, "text-muted-foreground")} when={at(invoice.issueDate)}>
          Issued for{" "}
          <Strong>
            <Money minor={invoice.total} currency={invoice.currency} locale={book.locale} />
          </Strong>
          , due {shortDate(invoice.dueDate)}
        </TimelineEvent>
      ),
    },
    ...(invoice.sentAt
      ? [
          {
            at: invoice.sentAt,
            node: (
              <TimelineEvent key="sent" icon={glyph(<Send />, "text-info")} when={at(invoice.sentAt)}>
                Sent to <Strong>{invoice.client.name}</Strong>
              </TimelineEvent>
            ),
          },
        ]
      : []),
    ...payments.map((p) => ({
      at: p.date,
      node: (
        <TimelineEvent key={p.transactionId} icon={glyph(<CircleCheck />, "text-success")} when={at(p.date)}>
          <Strong>
            <Money
              minor={p.amount}
              currency={invoice.currency}
              locale={book.locale}
              direction={p.amount >= 0 ? "in" : "out"}
            />
          </Strong>{" "}
          received to <Strong>{p.account.name}</Strong>
          {p.reconciled ? " · reconciled" : ""}
          <span className="text-subtle-foreground font-mono"> · {p.transactionId}</span>
        </TimelineEvent>
      ),
    })),
    ...(invoice.voidedAt
      ? [
          {
            at: invoice.voidedAt,
            node: (
              <TimelineEvent key="void" icon={glyph(<Ban />, "text-muted-foreground")} when={at(invoice.voidedAt)}>
                Voided; no longer owed
              </TimelineEvent>
            ),
          },
        ]
      : []),
  ].toSorted((a, b) => a.at.localeCompare(b.at));

  return (
    <Section
      title="Activity"
      meta={
        payments.length ? `${payments.length} ${payments.length === 1 ? "payment" : "payments"}` : "no payments yet"
      }
      className="gap-3 print:hidden"
    >
      <Timeline>{items.map((item) => item.node)}</Timeline>
    </Section>
  );
}
