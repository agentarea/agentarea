import type { InvoiceView } from "@shared/schema";
import { BookOpen, ChevronRight, FileText } from "lucide-react";
import { useState } from "react";
import { ErrorBanner, FieldNote, type Status } from "@kit/components/notes";
import { DetailLayout } from "@kit/components/properties";
import { DetailSkeleton } from "@kit/components/skeletons";
import { StandaloneNotice } from "@kit/components/standalone-notice";
import { Breadcrumb, Page, RefreshButton } from "@kit/components/view-header";
import { call, messageOf, openAppView, useView } from "@kit/lib/mcp";
import { TooltipProvider } from "@kit/ui/tooltip";
import { InvoiceDocument } from "@/components/invoice/invoice-document";
import { InvoiceHistory } from "@/components/invoice/invoice-history";
import { InvoiceProperties, type PaymentForm } from "@/components/invoice/invoice-properties";
import { shortDate } from "@/lib/format";

export function InvoiceApp() {
  if (window.parent === window) return <StandaloneNotice title="Invoice" icon={FileText} server="books" />;
  return <ConnectedInvoice />;
}

function ConnectedInvoice() {
  const [number, setNumber] = useState<string | null>(null);
  const {
    app,
    payload: view,
    setPayload,
    error,
  } = useView<InvoiceView>("Invoice", (input) => {
    if (typeof input.number === "string") setNumber(input.number);
  });
  const [status, setStatus] = useState<Status>(null);
  const [busy, setBusy] = useState(false);
  const [link, setLink] = useState<string | null>(null);
  const current = view?.invoice.number ?? number;

  /** Runs one action and shows the invoice it leaves behind; reports the outcome next to the buttons. */
  const act = async (label: string, done: string, run: () => Promise<InvoiceView>): Promise<boolean> => {
    if (!app || busy) return false;
    setBusy(true);
    setStatus({ kind: "busy", text: label });
    try {
      setPayload(await run());
      setStatus({ kind: "ok", text: done });
      return true;
    } catch (failure) {
      setStatus({ kind: "error", text: messageOf(failure) });
      return false;
    } finally {
      setBusy(false);
    }
  };
  const refetch = () => call<InvoiceView>(app!, "show_invoice", { number: current });

  const openLink = async (tool: string, args: Record<string, string>) =>
    setLink(app ? await openAppView(app, tool, args) : "Not connected to a host");

  return (
    <TooltipProvider>
      <Page width="detail" className="print:p-0">
        <ErrorBanner message={error} />
        {view ? (
          <div className="flex flex-col gap-4">
            <header className="flex flex-col gap-1 print:hidden">
              <div className="flex items-center gap-2">
                <Breadcrumb>
                  <button
                    type="button"
                    onClick={() => void openLink("show_books_overview", {})}
                    className="hover:text-foreground inline-flex min-w-0 cursor-pointer items-center gap-1.5 truncate"
                  >
                    <BookOpen className="size-3.5 shrink-0" />
                    <span className="truncate">{view.book.name}</span>
                  </button>
                  <ChevronRight className="size-3 shrink-0" />
                  <span className="text-foreground font-mono font-medium">{view.invoice.number}</span>
                </Breadcrumb>
                <RefreshButton
                  compact
                  className="ml-auto"
                  busy={busy || !current}
                  onClick={() => void act("Refreshing…", "Up to date", refetch)}
                  label="Reload from the books server"
                />
              </div>
              <FieldNote note={link} />
            </header>
            <div className="flex flex-col gap-1 print:hidden">
              <h1 className="text-xl leading-snug font-semibold tracking-tight">{view.invoice.client.name}</h1>
              <p className="text-muted-foreground tabular text-sm">
                Invoice {view.invoice.number} · issued {shortDate(view.invoice.issueDate)} · due{" "}
                {shortDate(view.invoice.dueDate)}
              </p>
            </div>
            <DetailLayout
              main={
                <>
                  <InvoiceDocument view={view} />
                  <InvoiceHistory view={view} />
                </>
              }
              aside={
                <InvoiceProperties
                  view={view}
                  status={status}
                  busy={busy}
                  onSend={() =>
                    void act("Marking as sent…", "Marked as sent", () =>
                      call<InvoiceView>(app!, "update_invoice", { number: view.invoice.number, action: "send" }),
                    )
                  }
                  onRecordPayment={(payment: PaymentForm) =>
                    act("Recording payment…", "Payment recorded", async () => {
                      await call(app!, "record_payment", {
                        number: view.invoice.number,
                        amount: payment.amount,
                        date: payment.date,
                        account: payment.account,
                      });
                      return refetch();
                    })
                  }
                  onVoid={() =>
                    act("Voiding…", "Invoice voided", () =>
                      call<InvoiceView>(app!, "update_invoice", { number: view.invoice.number, action: "void" }),
                    )
                  }
                  onOpenLedger={async () => {
                    const failure = await openAppView(app!, "show_transactions", { text: view.invoice.number });
                    if (failure) setStatus({ kind: "error", text: failure });
                  }}
                />
              }
            />
          </div>
        ) : (
          !error && <DetailSkeleton label="Loading invoice" />
        )}
      </Page>
    </TooltipProvider>
  );
}
