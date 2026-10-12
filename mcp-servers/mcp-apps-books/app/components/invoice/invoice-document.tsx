import type { InvoiceStatus } from "@shared/books";
import type { InvoiceView } from "@shared/schema";
import { Money } from "@/components/money";
import { Chip, type Tone } from "@kit/components/chip";
import { money, shortDate } from "@/lib/format";
import { cn } from "@kit/lib/utils";

export const STATUS_META: Record<InvoiceStatus, { label: string; tone: Tone }> = {
  draft: { label: "Draft", tone: "neutral" },
  sent: { label: "Sent", tone: "info" },
  partially_paid: { label: "Partially paid", tone: "warning" },
  overdue: { label: "Overdue", tone: "danger" },
  paid: { label: "Paid", tone: "success" },
  void: { label: "Void", tone: "neutral" },
};

/** The invoice as it would print: seller, client, lines, VAT and totals. */
export function InvoiceDocument({ view }: { view: InvoiceView }) {
  const { invoice, book } = view;
  const status = STATUS_META[invoice.status];
  const m = (minor: number, className?: string) => (
    <Money minor={minor} currency={invoice.currency} locale={book.locale} className={className} />
  );
  const quantity = new Intl.NumberFormat(book.locale, { maximumFractionDigits: 3 });

  return (
    <article
      className="bg-card w-full rounded-lg border px-4 py-5 sm:px-8 sm:py-7 print:border-0"
      aria-label="Invoice document"
    >
      {invoice.status === "void" && (
        <div className="bg-muted text-muted-foreground mb-6 rounded-md px-3 py-2 text-center text-xs font-medium">
          This invoice is void{invoice.voidedAt ? ` since ${shortDate(invoice.voidedAt.slice(0, 10))}` : ""}; it is not
          owed.
        </div>
      )}
      <header className="flex flex-col-reverse justify-between gap-6 sm:flex-row">
        <div className="min-w-0 text-xs leading-relaxed">
          <div className="text-foreground text-sm font-semibold">{book.legalName}</div>
          {book.address && <div className="text-muted-foreground">{book.address}</div>}
          {book.taxId && <div className="text-muted-foreground tabular">INN {book.taxId}</div>}
          {book.email && <div className="text-muted-foreground">{book.email}</div>}
        </div>
        <div className="sm:text-right">
          <div className="text-muted-foreground text-xs">Invoice</div>
          <div className="tabular mt-1 text-xl font-semibold tracking-tight">{invoice.number}</div>
          <Chip tone={status.tone} className="mt-2">
            {status.label}
            {invoice.status === "overdue" && ` · ${invoice.daysOverdue} days`}
          </Chip>
        </div>
      </header>

      <dl className="mt-6 grid gap-5 text-xs sm:grid-cols-[2fr_1fr_1fr]">
        <div className="min-w-0">
          <dt className="text-muted-foreground mb-1 text-xs">Bill to</dt>
          <dd className="text-foreground text-sm font-medium">{invoice.client.name}</dd>
          {invoice.client.taxId && <dd className="text-muted-foreground tabular">INN {invoice.client.taxId}</dd>}
          {invoice.client.email && <dd className="text-muted-foreground">{invoice.client.email}</dd>}
        </div>
        <div>
          <dt className="text-muted-foreground mb-1 text-xs">Issued</dt>
          <dd className="tabular text-sm">{shortDate(invoice.issueDate)}</dd>
        </div>
        <div>
          <dt className="text-muted-foreground mb-1 text-xs">Due</dt>
          <dd className={cn("tabular text-sm", invoice.status === "overdue" && "text-danger font-medium")}>
            {shortDate(invoice.dueDate)}
          </dd>
        </div>
      </dl>

      <div className="mt-6 overflow-x-auto">
        <table className="w-full min-w-[520px] text-[13px]">
          <thead>
            <tr className="text-muted-foreground border-b text-left text-xs font-medium">
              <th className="w-8 py-2 pr-2 font-medium">#</th>
              <th className="py-2 pr-4 font-medium">Description</th>
              <th className="py-2 pr-4 text-right font-medium">Qty</th>
              <th className="py-2 pr-4 text-right font-medium">Unit price</th>
              <th className="py-2 pr-4 text-right font-medium">VAT</th>
              <th className="py-2 text-right font-medium">Amount</th>
            </tr>
          </thead>
          <tbody>
            {invoice.lines.map((line, index) => (
              <tr key={index} className="border-b align-top last:border-0">
                <td className="text-subtle-foreground tabular py-2.5 pr-2">{index + 1}</td>
                <td className="py-2.5 pr-4">{line.description}</td>
                <td className="tabular py-2.5 pr-4 text-right">{quantity.format(line.quantity)}</td>
                <td className="py-2.5 pr-4 text-right">{m(line.unitPrice)}</td>
                <td className="text-muted-foreground tabular py-2.5 pr-4 text-right">
                  {line.vatRate ? `${line.vatRate}%` : "—"}
                </td>
                <td className="py-2.5 text-right">{m(line.net)}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>

      <div className="mt-4 flex justify-end">
        <dl className="w-full max-w-[320px] text-[13px]">
          <div className="flex justify-between py-1">
            <dt className="text-muted-foreground">Subtotal</dt>
            <dd>{m(invoice.subtotal)}</dd>
          </div>
          {invoice.vatBreakdown.map((row) => (
            <div key={row.rate ?? "none"} className="flex justify-between py-1">
              <dt className="text-muted-foreground">
                {row.rate ? `VAT ${row.rate}% on ${money(row.net, invoice.currency, book.locale)}` : "No VAT"}
              </dt>
              <dd>{m(row.vat)}</dd>
            </div>
          ))}
          <div className="mt-1 flex justify-between border-t pt-2 text-sm font-semibold">
            <dt>Total</dt>
            <dd>{m(invoice.total)}</dd>
          </div>
          {invoice.amountPaid !== 0 && (
            <div className="flex justify-between py-1">
              <dt className="text-muted-foreground">Paid</dt>
              <dd>
                <Money minor={invoice.amountPaid} currency={invoice.currency} locale={book.locale} direction="out" />
              </dd>
            </div>
          )}
          {invoice.status !== "void" && (
            <div className="bg-muted/60 mt-1 flex justify-between rounded-md px-2 py-2 font-semibold">
              <dt>Balance due</dt>
              <dd>{m(invoice.balanceDue, invoice.status === "overdue" ? "text-danger" : undefined)}</dd>
            </div>
          )}
        </dl>
      </div>

      {(invoice.notes || book.bankDetails) && (
        <footer className="text-muted-foreground mt-8 grid gap-4 border-t pt-5 text-xs leading-relaxed sm:grid-cols-2">
          {book.bankDetails && (
            <div>
              <div className="text-muted-foreground mb-1 text-xs">Payment details</div>
              <div className="tabular">{book.bankDetails}</div>
              <div>Reference: {invoice.number}</div>
            </div>
          )}
          {invoice.notes && (
            <div>
              <div className="text-muted-foreground mb-1 text-xs">Notes</div>
              <div>{invoice.notes}</div>
            </div>
          )}
        </footer>
      )}
    </article>
  );
}
