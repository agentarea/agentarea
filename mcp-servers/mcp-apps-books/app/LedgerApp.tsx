import type { CategorizeResult, Ledger, TransactionRow } from "@shared/schema";
import { ListFrame } from "@kit/components/list";
import { ErrorBanner } from "@kit/components/notes";
import { ListSkeleton } from "@kit/components/skeletons";
import { Page, RefreshButton, ViewHeader } from "@kit/components/view-header";
import { Plus, ReceiptText } from "lucide-react";
import { useCallback, useEffect, useRef, useState } from "react";
import { InlineStatus, type Status } from "@kit/components/notes";
import { AddRow, type NewTransaction } from "@/components/ledger/add-row";
import { BulkBar } from "@/components/ledger/bulk-bar";
import {
  EMPTY_FILTERS,
  FilterBar,
  fromLedgerFilters,
  toolArgs,
  type FilterState,
} from "@/components/ledger/filter-bar";
import { LedgerTable } from "@/components/ledger/ledger-table";
import { Money } from "@/components/money";
import { StandaloneNotice } from "@kit/components/standalone-notice";
import { Button } from "@kit/ui/button";
import { TooltipProvider } from "@kit/ui/tooltip";
import { call, messageOf, openAppView, useView } from "@kit/lib/mcp";

export function LedgerApp() {
  if (window.parent === window) return <StandaloneNotice title="Transactions" icon={ReceiptText} server="books" />;
  return <ConnectedLedger />;
}

const LIMIT = 1000;

function ConnectedLedger() {
  const { app, isConnected, payload: ledger, setPayload, error, setError } = useView<Ledger>("Transactions");
  const [filters, setFilters] = useState<FilterState | null>(null);
  const [loading, setLoading] = useState(false);
  const [selected, setSelected] = useState<Set<string>>(new Set());
  const [rowStatus, setRowStatus] = useState<Record<string, Status>>({});
  const [bulkStatus, setBulkStatus] = useState<Status>(null);
  const [viewStatus, setViewStatus] = useState<Status>(null);
  const [adding, setAdding] = useState(false);
  const request = useRef(0);

  const load = useCallback(
    async (next: FilterState, quiet = false) => {
      if (!app) return;
      const id = ++request.current;
      if (!quiet) setLoading(true);
      try {
        const result = await call<Ledger>(app, "show_transactions", { ...toolArgs(next), limit: LIMIT });
        if (id !== request.current) return;
        setPayload(result);
        setError(null);
      } catch (failure) {
        if (id === request.current) setError(messageOf(failure));
      } finally {
        if (id === request.current) setLoading(false);
      }
    },
    [app, setPayload, setError],
  );

  // The filters start from whatever the entry tool resolved; without a result, load everything.
  useEffect(() => {
    if (ledger && filters === null) setFilters(fromLedgerFilters(ledger.filters));
  }, [ledger, filters]);
  useEffect(() => {
    if (!isConnected || ledger) return;
    const timer = window.setTimeout(() => {
      if (request.current === 0) {
        setFilters(EMPTY_FILTERS);
        void load(EMPTY_FILTERS);
      }
    }, 1500);
    return () => window.clearTimeout(timer);
  }, [isConnected, ledger, load]);

  const changeFilters = (next: FilterState) => {
    setFilters(next);
    setSelected(new Set());
  };
  // Typing in search waits for a pause; every other filter applies at once.
  useEffect(() => {
    if (!filters || !ledger) return;
    const applied = fromLedgerFilters(ledger.filters);
    if (JSON.stringify(toolArgs(filters)) === JSON.stringify(toolArgs(applied))) return;
    const timer = window.setTimeout(() => void load(filters), filters.text.trim() !== applied.text ? 300 : 0);
    return () => window.clearTimeout(timer);
  }, [filters, ledger, load]);

  const replaceRows = (updated: TransactionRow[], uncategorizedCount?: number) =>
    setPayload((current) => {
      if (!current) return current;
      const byId = new Map(updated.map((r) => [r.id, r]));
      return {
        ...current,
        rows: current.rows.map((r) => byId.get(r.id) ?? r),
        uncategorizedCount: uncategorizedCount ?? current.uncategorizedCount,
      };
    });
  const setStatusFor = (ids: string[], status: Status) =>
    setRowStatus((current) => ({ ...current, ...Object.fromEntries(ids.map((id) => [id, status])) }));

  const categorize = async (row: TransactionRow, categoryId: string) => {
    if (!app) return;
    setStatusFor([row.id], { kind: "busy", text: "Saving…" });
    try {
      const result = await call<CategorizeResult>(app, "categorize_transactions", {
        ids: [row.id],
        category: categoryId || null,
      });
      replaceRows(result.transactions, result.remainingUncategorized);
      setStatusFor([row.id], null);
    } catch (failure) {
      setStatusFor([row.id], { kind: "error", text: messageOf(failure) });
    }
  };

  const reconcile = async (ids: string[], reconciled: boolean) => {
    if (!app) return;
    await call(app, "set_reconciled", { ids, reconciled });
    setPayload(
      (current) =>
        current && { ...current, rows: current.rows.map((r) => (ids.includes(r.id) ? { ...r, reconciled } : r)) },
    );
  };

  const toggleReconciled = async (row: TransactionRow) => {
    try {
      await reconcile([row.id], !row.reconciled);
      setStatusFor([row.id], null);
    } catch (failure) {
      setStatusFor([row.id], { kind: "error", text: messageOf(failure) });
    }
  };

  const bulkCategorize = async (categoryId: string, counterpartyId: string | null) => {
    if (!app) return;
    const ids = [...selected];
    setBulkStatus({ kind: "busy", text: `Categorizing ${ids.length}…` });
    try {
      const result = await call<CategorizeResult>(app, "categorize_transactions", {
        ids,
        category: categoryId,
        ...(counterpartyId ? { counterparty: counterpartyId } : {}),
      });
      replaceRows(result.transactions, result.remainingUncategorized);
      setSelected(new Set());
      setBulkStatus(null);
      setViewStatus({
        kind: "ok",
        text: `${result.updated} categorized as ${result.category?.name}; ${result.remainingUncategorized} left to review`,
      });
    } catch (failure) {
      setBulkStatus({ kind: "error", text: messageOf(failure) });
    }
  };

  const bulkReconcile = async () => {
    const ids = [...selected];
    setBulkStatus({ kind: "busy", text: `Reconciling ${ids.length}…` });
    try {
      await reconcile(ids, true);
      setSelected(new Set());
      setBulkStatus(null);
      setViewStatus({ kind: "ok", text: `${ids.length} marked reconciled` });
    } catch (failure) {
      setBulkStatus({ kind: "error", text: messageOf(failure) });
    }
  };

  const add = async (input: NewTransaction): Promise<string | null> => {
    if (!app || !filters) return "Not connected";
    try {
      await call(app, "record_transaction", input);
      await load(filters, true);
      return null;
    } catch (failure) {
      return messageOf(failure);
    }
  };

  const openInvoice = async (number: string) => {
    if (!app) return;
    const failure = await openAppView(app, "show_invoice", { number });
    setViewStatus(failure ? { kind: "error", text: failure } : null);
  };

  const locale = ledger?.book.locale ?? "ru-RU";
  const base = ledger?.baseCurrency ?? "RUB";

  return (
    <TooltipProvider>
      <Page>
        <ViewHeader
          icon={ReceiptText}
          title="Transactions"
          subtitle={
            ledger ? (
              <>
                {ledger.book.name} · {ledger.total} matching
                {ledger.uncategorizedCount > 0 && (
                  <span className="text-warning"> · {ledger.uncategorizedCount} to review</span>
                )}
              </>
            ) : (
              "Connecting to the books server…"
            )
          }
          actions={
            <>
              <Button
                size="sm"
                onClick={() => setAdding(true)}
                disabled={!ledger || adding}
                aria-label="Add transaction"
              >
                <Plus />
                <span className="hidden sm:inline">Add transaction</span>
              </Button>
              <RefreshButton
                busy={loading || !filters}
                onClick={() => filters && void load(filters)}
                label="Reload from the books server"
              />
            </>
          }
        />

        <ErrorBanner message={error} />

        {ledger && filters ? (
          <>
            <FilterBar ledger={ledger} filters={filters} onChange={changeFilters} />
            <div className="flex flex-wrap items-center gap-x-5 gap-y-1 text-xs">
              <span className="text-muted-foreground">
                In{" "}
                <Money
                  minor={ledger.totals.in}
                  currency={base}
                  locale={locale}
                  direction="in"
                  className="font-medium"
                />
              </span>
              <span className="text-muted-foreground">
                Out{" "}
                <Money
                  minor={ledger.totals.out}
                  currency={base}
                  locale={locale}
                  direction="out"
                  className="text-foreground font-medium"
                />
              </span>
              <span className="text-muted-foreground">
                Net <Money minor={ledger.totals.net} currency={base} locale={locale} className="font-semibold" />
              </span>
              <span className="text-subtle-foreground">transfers excluded</span>
              <InlineStatus status={viewStatus} />
            </div>
            <ListFrame
              className="transition-opacity data-[loading=true]:opacity-60"
              data-loading={loading}
              aria-busy={loading}
            >
              {selected.size > 0 && (
                <BulkBar
                  ledger={ledger}
                  count={selected.size}
                  status={bulkStatus}
                  onCategorize={(category, counterparty) => void bulkCategorize(category, counterparty)}
                  onReconcile={() => void bulkReconcile()}
                  onClear={() => setSelected(new Set())}
                />
              )}
              <LedgerTable
                ledger={ledger}
                selected={selected}
                onSelect={(ids, on) =>
                  setSelected((current) => {
                    const next = new Set(current);
                    for (const id of ids) {
                      if (on) next.add(id);
                      else next.delete(id);
                    }
                    return next;
                  })
                }
                rowStatus={rowStatus}
                onCategorize={(row, category) => void categorize(row, category)}
                onReconcile={(row) => void toggleReconciled(row)}
                onOpenInvoice={(number) => void openInvoice(number)}
                addRow={adding ? <AddRow ledger={ledger} onSubmit={add} onClose={() => setAdding(false)} /> : null}
              />
            </ListFrame>
          </>
        ) : (
          !error && <ListSkeleton rows={14} label="Loading transactions" />
        )}
      </Page>
    </TooltipProvider>
  );
}
