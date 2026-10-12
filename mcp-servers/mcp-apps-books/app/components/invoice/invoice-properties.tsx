import { Chip } from "@kit/components/chip";
import { InlineStatus, type Status } from "@kit/components/notes";
import { PropertyFooter, PropertyPanel, PropertyRow as Row, PropertyValue } from "@kit/components/properties";
import { cn } from "@kit/lib/utils";
import { Button } from "@kit/ui/button";
import { Input } from "@kit/ui/input";
import { NativeSelect } from "@kit/ui/native-select";
import { toMajor } from "@shared/money";
import type { InvoiceView } from "@shared/schema";
import { Ban, Banknote, Printer, ReceiptText, Send } from "lucide-react";
import { useState, type FormEvent } from "react";
import { Money } from "@/components/money";
import { shortDate } from "@/lib/format";
import { STATUS_META } from "./invoice-document";

export type PaymentForm = { amount: string; date: string; account: string };

type Mode = "idle" | "payment" | "void";

export function InvoiceProperties({
  view,
  status,
  busy,
  onSend,
  onRecordPayment,
  onVoid,
  onOpenLedger,
}: {
  view: InvoiceView;
  status: Status;
  busy: boolean;
  onSend: () => void;
  onRecordPayment: (payment: PaymentForm) => Promise<boolean>;
  onVoid: () => Promise<boolean>;
  onOpenLedger: () => void;
}) {
  const { invoice, book } = view;
  const [mode, setMode] = useState<Mode>("idle");
  const [payment, setPayment] = useState<PaymentForm>({
    amount: "",
    date: view.today,
    account: view.accounts[0]?.id ?? "",
  });
  const canPay = invoice.status === "sent" || invoice.status === "partially_paid" || invoice.status === "overdue";
  const canVoid = invoice.status !== "void" && view.payments.length === 0;
  const m = (minor: number, className?: string) => (
    <Money minor={minor} currency={invoice.currency} locale={book.locale} className={className} />
  );

  const startPayment = () => {
    setPayment({
      amount: String(toMajor(invoice.balanceDue, invoice.currency)).replace(".", ","),
      date: view.today,
      account: view.accounts[0]?.id ?? "",
    });
    setMode("payment");
  };
  const submitPayment = async (event: FormEvent) => {
    event.preventDefault();
    if (await onRecordPayment(payment)) setMode("idle");
  };

  return (
    <PropertyPanel className="print:hidden">
      <Row label="Status">
        <div className="flex flex-wrap items-center gap-1 pt-1">
          <Chip tone={STATUS_META[invoice.status].tone}>{STATUS_META[invoice.status].label}</Chip>
          {invoice.status === "overdue" && (
            <span className="text-danger tabular text-[11px]">{invoice.daysOverdue} days late</span>
          )}
        </div>
      </Row>
      <Row label="Client">
        <PropertyValue className="truncate">{invoice.client.name}</PropertyValue>
      </Row>
      <Row label="Issued">
        <PropertyValue className="tabular">{shortDate(invoice.issueDate)}</PropertyValue>
      </Row>
      <Row label="Due">
        <PropertyValue className={cn("tabular", invoice.status === "overdue" && "text-danger")}>
          {shortDate(invoice.dueDate)}
        </PropertyValue>
      </Row>
      <Row label="Total">
        <PropertyValue>{m(invoice.total)}</PropertyValue>
      </Row>
      {invoice.amountPaid !== 0 && (
        <Row label="Paid">
          <PropertyValue>{m(invoice.amountPaid)}</PropertyValue>
        </Row>
      )}
      {invoice.status !== "void" && (
        <Row label="Balance">
          <PropertyValue>
            {m(invoice.balanceDue, cn("font-semibold", invoice.status === "overdue" && "text-danger"))}
          </PropertyValue>
        </Row>
      )}
      {invoice.category && (
        <Row label="Booked to">
          <PropertyValue className="truncate">{invoice.category.name}</PropertyValue>
        </Row>
      )}

      <div className="flex flex-col gap-2 border-t pt-3">
        <div className="grid grid-cols-2 gap-1.5">
          {invoice.status === "draft" && (
            <Button size="xs" onClick={onSend} disabled={busy}>
              <Send />
              Mark as sent
            </Button>
          )}
          {canPay && (
            <Button
              size="xs"
              variant={mode === "payment" ? "secondary" : "default"}
              onClick={startPayment}
              disabled={busy}
            >
              <Banknote />
              Record payment
            </Button>
          )}
          {canVoid && (
            <Button size="xs" variant="outline" onClick={() => setMode("void")} disabled={busy}>
              <Ban />
              Void
            </Button>
          )}
          <Button size="xs" variant="outline" onClick={onOpenLedger}>
            <ReceiptText />
            In the ledger
          </Button>
          <Button size="xs" variant="outline" onClick={() => window.print()}>
            <Printer />
            Print
          </Button>
        </div>

        {mode === "payment" && (
          <form onSubmit={submitPayment} className="bg-muted/70 flex flex-col gap-2 rounded-md border p-2">
            <label className="flex flex-col gap-1 text-xs">
              <span className="text-muted-foreground">Amount, {invoice.currency}</span>
              <Input
                inputMode="decimal"
                value={payment.amount}
                onChange={(e) => setPayment({ ...payment, amount: e.target.value })}
                className="tabular h-7 text-right text-xs"
                required
                autoFocus
              />
            </label>
            <label className="flex flex-col gap-1 text-xs">
              <span className="text-muted-foreground">Received on</span>
              <Input
                type="date"
                value={payment.date}
                onChange={(e) => setPayment({ ...payment, date: e.target.value })}
                className="tabular h-7 text-xs"
                required
              />
            </label>
            <label className="flex flex-col gap-1 text-xs">
              <span className="text-muted-foreground">Into account</span>
              <NativeSelect
                size="sm"
                value={payment.account}
                onChange={(e) => setPayment({ ...payment, account: e.target.value })}
                className="w-full"
              >
                {view.accounts.map((a) => (
                  <option key={a.id} value={a.id}>
                    {a.name}
                  </option>
                ))}
              </NativeSelect>
            </label>
            {view.accounts.length === 0 && (
              <p className="text-danger text-[11px]">No account in {invoice.currency} can receive this payment.</p>
            )}
            <div className="flex items-center justify-end gap-1.5">
              <Button type="button" size="xs" variant="ghost" onClick={() => setMode("idle")}>
                Cancel
              </Button>
              <Button type="submit" size="xs" disabled={busy || view.accounts.length === 0}>
                Save payment
              </Button>
            </div>
          </form>
        )}

        {mode === "void" && (
          <div className="border-danger/30 bg-danger-surface flex flex-col gap-2 rounded-md border p-2 text-xs">
            <p>
              Void {invoice.number}? It stays in the books for the record but is no longer owed. This cannot be undone.
            </p>
            <div className="flex items-center justify-end gap-1.5">
              <Button size="xs" variant="ghost" onClick={() => setMode("idle")}>
                Keep it
              </Button>
              <Button
                size="xs"
                variant="destructive"
                disabled={busy}
                onClick={async () => (await onVoid()) && setMode("idle")}
              >
                Void invoice
              </Button>
            </div>
          </div>
        )}
        <InlineStatus status={status} />
      </div>

      <PropertyFooter>
        <span className="font-mono">{invoice.number}</span>
        <span>{book.legalName}</span>
      </PropertyFooter>
    </PropertyPanel>
  );
}
