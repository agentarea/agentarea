/**
 * What each tool returns: the structured payload a view renders, and the
 * short text a model reads next to it.
 */
import type { BooksData, Invoice, InvoiceStatus, PeriodKind } from "../shared/books.ts";
import { formatMoney } from "../shared/money.ts";
import { addMonths, monthsBetween, resolvePeriod, shiftPeriod, type Period } from "../shared/period.ts";
import type {
  InvoiceList,
  InvoiceSummary,
  InvoiceView,
  Ledger,
  LedgerFilters,
  Overview,
  Reference,
  Report,
  TransactionList,
  TransactionRow,
} from "../shared/schema.ts";
import {
  accountSummaries,
  cashflow,
  cashOnHand,
  cashSeries,
  filterTransactions,
  invoicePayments,
  invoiceSummary,
  invoiceTotals,
  monthlyIncomeExpense,
  profitAndLoss,
  receivablesAging,
  todayOf,
  totalsOf,
  transactionRow,
  uncategorized,
} from "./ledger.ts";

const moneyIn = (data: BooksData) => (minor: number, currency = data.book.baseCurrency) =>
  formatMoney(minor, currency, data.book.locale);

export function periodOf(data: BooksData, kind: PeriodKind = "month", date?: string, from?: string, to?: string): Period {
  return resolvePeriod(kind, date ?? todayOf(data), from, to);
}

// ---------------------------------------------------------------------------
// Overview
// ---------------------------------------------------------------------------

export function buildOverview(data: BooksData, period: Period): Overview {
  const today = todayOf(data);
  const previous = shiftPeriod(period, -1);
  const pnl = profitAndLoss(data, period.from, period.to);
  const prevPnl = profitAndLoss(data, previous.from, previous.to, 0);
  const cashAsOf = period.to < today ? period.to : today;
  const aging = receivablesAging(data, today);
  const base = data.book.baseCurrency;
  const agingBase = aging.totals.find((t) => t.currency === base) ?? {
    currency: base,
    current: 0,
    d1_30: 0,
    d31_60: 0,
    d60_plus: 0,
    total: 0,
  };
  const open = aging.invoices.filter((i) => i.currency === base);
  const overdue = open.filter((i) => i.status === "overdue");
  const chartFrom = addMonths(`${period.to.slice(0, 7)}-01`, -11);
  const inPeriod = new Set(monthsBetween(period.from, period.to));
  const pending = uncategorized(data).sort((a, b) => a.date.localeCompare(b.date));
  const seriesFrom = period.from;
  const seriesTo = cashAsOf < period.from ? period.from : cashAsOf;

  return {
    book: data.book,
    today,
    period,
    previous: { ...previous, income: prevPnl.totalIncome, expenses: prevPnl.totalExpenses, net: prevPnl.net },
    kpis: {
      cash: cashOnHand(data, cashAsOf),
      cashAsOf,
      income: pnl.totalIncome,
      expenses: pnl.totalExpenses,
      net: pnl.net,
      receivables: agingBase.total,
      receivablesCount: open.length,
      overdue: agingBase.total - agingBase.current,
      overdueCount: overdue.length,
    },
    months: monthlyIncomeExpense(data, chartFrom, period.to).map((m) => ({ ...m, inPeriod: inPeriod.has(m.month) })),
    pnl,
    accounts: accountSummaries(data, cashAsOf).filter((a) => !a.archived),
    cashSeries: cashSeries(data, seriesFrom, seriesTo),
    uncategorized: { count: pending.length, oldest: pending[0]?.date ?? null },
    overdueInvoices: aging.invoices
      .filter((i) => i.status === "overdue")
      .map(({ bucket: _bucket, ...invoice }) => invoice),
    aging: agingBase,
  };
}

export function summarizeOverview(o: Overview, data: BooksData): string {
  const m = moneyIn(data);
  const lines = [
    `${o.book.name} · ${o.period.label} (${o.period.from} – ${o.period.to}), today ${o.today}`,
    `Cash on hand ${m(o.kpis.cash)} (as of ${o.kpis.cashAsOf}): ` +
      o.accounts.map((a) => `${a.name} ${m(a.balance, a.currency)}`).join(", "),
    `Income ${m(o.kpis.income)} · Expenses ${m(o.kpis.expenses)} · Net ${m(o.kpis.net)} ` +
      `(previous ${o.previous.label}: net ${m(o.previous.net)})`,
    `Receivables ${m(o.kpis.receivables)} in ${o.kpis.receivablesCount} invoices, overdue ${m(o.kpis.overdue)} in ${o.kpis.overdueCount}`,
  ];
  if (o.pnl.expenses.length > 0) {
    lines.push(
      `Largest expenses: ${o.pnl.expenses
        .slice(0, 4)
        .map((l) => `${l.name} ${m(l.amount)}`)
        .join(", ")}`,
    );
  }
  if (o.uncategorized.count > 0) {
    lines.push(
      `Needs review: ${o.uncategorized.count} uncategorized transactions since ${o.uncategorized.oldest} ` +
        "(list_transactions uncategorized=true, then categorize_transactions)",
    );
  }
  for (const invoice of o.overdueInvoices.slice(0, 5)) {
    lines.push(
      `Overdue: ${invoice.number} ${invoice.client.name} ${m(invoice.balanceDue, invoice.currency)}, ${invoice.daysOverdue} days late`,
    );
  }
  return lines.join("\n");
}

// ---------------------------------------------------------------------------
// Transactions
// ---------------------------------------------------------------------------

export function buildTransactionList(data: BooksData, filters: LedgerFilters, offset: number, limit: number): TransactionList {
  const matching = filterTransactions(data, filters);
  return {
    today: todayOf(data),
    baseCurrency: data.book.baseCurrency,
    filters,
    total: matching.length,
    offset,
    limit,
    totals: totalsOf(matching),
    rows: matching.slice(offset, offset + limit).map((t) => transactionRow(data, t)),
  };
}

export function buildLedger(data: BooksData, filters: LedgerFilters, offset: number, limit: number): Ledger {
  return {
    ...buildTransactionList(data, filters, offset, limit),
    book: data.book,
    uncategorizedCount: uncategorized(data).length,
    accounts: data.accounts.map((a) => ({ id: a.id, name: a.name, currency: a.currency, kind: a.kind, archived: a.archived })),
    categories: data.categories,
    counterparties: data.counterparties
      .map((c) => ({ id: c.id, name: c.name, kind: c.kind }))
      .sort((a, b) => a.name.localeCompare(b.name)),
  };
}

export function describeRow(row: TransactionRow, data: BooksData): string {
  const m = moneyIn(data);
  const sign = row.direction === "in" ? "+" : row.direction === "out" ? "−" : "⇄";
  const amount = `${sign}${m(row.amount, row.currency)}`;
  const base = row.currency !== data.book.baseCurrency ? ` (${m(row.baseAmount)})` : "";
  const where =
    row.direction === "transfer" ? `${row.account.name} → ${row.transferAccount?.name}` : row.account.name;
  const parts = [
    row.id,
    row.date,
    where,
    amount + base,
    row.counterparty?.name ?? "no counterparty",
    row.direction === "transfer" ? "transfer" : (row.category?.name ?? "UNCATEGORIZED"),
    `"${row.description}"`,
  ];
  if (row.invoice) parts.push(`pays ${row.invoice.number}`);
  if (row.reconciled) parts.push("reconciled");
  return parts.join(" | ");
}

export function describeFilters(f: LedgerFilters): string {
  const parts: string[] = [];
  if (f.from || f.to) parts.push(`${f.from ?? "…"} – ${f.to ?? "…"}`);
  if (f.account) parts.push(`account ${f.account}`);
  if (f.uncategorized) parts.push("uncategorized");
  if (f.category) parts.push(`category ${f.category}`);
  if (f.counterparty) parts.push(`counterparty ${f.counterparty}`);
  if (f.direction) parts.push(f.direction);
  if (f.reconciled !== null) parts.push(f.reconciled ? "reconciled" : "unreconciled");
  if (f.text) parts.push(`"${f.text}"`);
  return parts.length ? parts.join(", ") : "all transactions";
}

export function summarizeTransactions(list: TransactionList, data: BooksData, maxRows = list.rows.length): string {
  const m = moneyIn(data);
  const head =
    `${list.total} transactions (${describeFilters(list.filters)}); in ${m(list.totals.in)}, out ${m(list.totals.out)}, ` +
    `net ${m(list.totals.net)}` +
    (list.total > list.offset + list.rows.length ? `; showing ${list.offset + 1}–${list.offset + list.rows.length}` : "");
  const rows = list.rows.slice(0, maxRows).map((row) => describeRow(row, data));
  const more = list.rows.length > maxRows ? [`… ${list.rows.length - maxRows} more in structured content`] : [];
  return [head, ...rows, ...more].join("\n");
}

// ---------------------------------------------------------------------------
// Invoices
// ---------------------------------------------------------------------------

export function buildInvoiceView(data: BooksData, invoice: Invoice): InvoiceView {
  const today = todayOf(data);
  const summary = invoiceSummary(data, invoice, today);
  const totals = invoiceTotals(invoice.lines);
  const client = data.counterparties.find((c) => c.id === invoice.counterpartyId);
  const category = invoice.categoryId ? data.categories.find((c) => c.id === invoice.categoryId) : undefined;
  return {
    book: data.book,
    today,
    invoice: {
      ...summary,
      client: {
        id: invoice.counterpartyId,
        name: client?.name ?? invoice.counterpartyId,
        taxId: client?.taxId ?? null,
        email: client?.email ?? null,
      },
      lines: totals.lines,
      subtotal: totals.subtotal,
      vatTotal: totals.vatTotal,
      vatBreakdown: totals.vatBreakdown,
      notes: invoice.notes,
      category: category ? { id: category.id, name: category.name } : null,
      sentAt: invoice.sentAt,
      voidedAt: invoice.voidedAt,
    },
    payments: invoicePayments(data, invoice.id).map((t) => ({
      transactionId: t.id,
      date: t.date,
      amount: t.direction === "in" ? t.amount : -t.amount,
      account: { id: t.accountId, name: data.accounts.find((a) => a.id === t.accountId)?.name ?? t.accountId },
      reconciled: t.reconciled,
    })),
    accounts: data.accounts
      .filter((a) => !a.archived && a.currency === invoice.currency)
      .map((a) => ({ id: a.id, name: a.name, currency: a.currency })),
  };
}

const STATUS_LABEL: Record<InvoiceStatus, string> = {
  draft: "draft",
  sent: "sent",
  partially_paid: "partially paid",
  overdue: "overdue",
  paid: "paid",
  void: "void",
};

export function describeInvoice(s: InvoiceSummary, data: BooksData): string {
  const m = moneyIn(data);
  const due =
    s.status === "overdue"
      ? `${s.daysOverdue} days overdue`
      : s.status === "paid" || s.status === "void"
        ? ""
        : `due ${s.dueDate}`;
  return [
    s.number,
    s.client.name,
    STATUS_LABEL[s.status],
    `total ${m(s.total, s.currency)}`,
    s.amountPaid ? `paid ${m(s.amountPaid, s.currency)}` : "",
    s.balanceDue && s.status !== "draft" ? `due now ${m(s.balanceDue, s.currency)}` : "",
    `issued ${s.issueDate}`,
    due,
  ]
    .filter(Boolean)
    .join(" | ");
}

export function summarizeInvoice(view: InvoiceView, data: BooksData): string {
  const m = moneyIn(data);
  const i = view.invoice;
  const lines = [
    describeInvoice(i, data),
    ...i.lines.map(
      (l) =>
        `  ${l.description}: ${l.quantity} × ${m(l.unitPrice, i.currency)} = ${m(l.net, i.currency)}` +
        (l.vatRate ? ` + VAT ${l.vatRate}% ${m(l.vat, i.currency)}` : " (no VAT)"),
    ),
    `Subtotal ${m(i.subtotal, i.currency)}, VAT ${m(i.vatTotal, i.currency)}, total ${m(i.total, i.currency)}`,
  ];
  for (const p of view.payments) lines.push(`Payment ${p.transactionId} ${p.date} ${m(p.amount, i.currency)} to ${p.account.name}`);
  return lines.join("\n");
}

export function buildInvoiceList(data: BooksData, statuses: InvoiceStatus[] | null, client: string | null): InvoiceList {
  const today = todayOf(data);
  const invoices = data.invoices
    .map((invoice) => invoiceSummary(data, invoice, today))
    .filter((s) => (!statuses || statuses.includes(s.status)) && (!client || s.client.id === client))
    .sort((a, b) => b.number.localeCompare(a.number));
  const outstanding = new Map<string, number>();
  for (const s of invoices) {
    if (s.status === "sent" || s.status === "partially_paid" || s.status === "overdue") {
      outstanding.set(s.currency, (outstanding.get(s.currency) ?? 0) + s.balanceDue);
    }
  }
  return {
    today,
    invoices,
    outstanding: [...outstanding.entries()].map(([currency, amount]) => ({ currency, amount })),
  };
}

// ---------------------------------------------------------------------------
// Reports
// ---------------------------------------------------------------------------

export function buildReport(data: BooksData, report: Report["report"], period: Period): Report {
  if (report === "receivables") {
    return { report, book: data.book, period: null, receivables: receivablesAging(data, todayOf(data)) };
  }
  if (report === "cashflow") return { report, book: data.book, period, cashflow: cashflow(data, period.from, period.to) };
  return { report, book: data.book, period, pnl: profitAndLoss(data, period.from, period.to, 10) };
}

export function summarizeReport(r: Report, data: BooksData): string {
  const m = moneyIn(data);
  if (r.pnl) {
    const p = r.pnl;
    const lines = [`Profit and loss, ${r.period!.label} (${p.from} – ${p.to}), cash basis, ${p.currency}`, "Income"];
    for (const l of p.income) lines.push(`  ${l.name}: ${m(l.amount)} (${l.count})`);
    lines.push(`  Total income: ${m(p.totalIncome)}`, "Expenses");
    for (const l of p.expenses) lines.push(`  ${l.name}: ${m(l.amount)} (${l.count})`);
    lines.push(`  Total expenses: ${m(p.totalExpenses)}`, `Net profit: ${m(p.net)}`);
    if (p.topVendors.length) {
      lines.push(`Top vendors: ${p.topVendors.map((v) => `${v.name} ${m(v.amount)}`).join(", ")}`);
    }
    return lines.join("\n");
  }
  if (r.cashflow) {
    const c = r.cashflow;
    const lines = [
      `Cash flow, ${r.period!.label} (${c.from} – ${c.to}), ${c.currency}: opening ${m(c.opening)}, ` +
        `in ${m(c.inflows)}, out ${m(c.outflows)}, closing ${m(c.closing)}`,
      ...c.months.map(
        (mo) => `  ${mo.label}: in ${m(mo.inflows)}, out ${m(mo.outflows)}, net ${m(mo.net)}, closing ${m(mo.closing)}`,
      ),
      ...c.accounts.map((a) => `  ${a.name}: ${m(a.opening, a.currency)} → ${m(a.closing, a.currency)}`),
    ];
    return lines.join("\n");
  }
  const a = r.receivables!;
  const lines = [`Receivables aging as of ${a.asOf}`];
  for (const t of a.totals) {
    lines.push(
      `  ${t.currency}: current ${m(t.current, t.currency)}, 1–30 ${m(t.d1_30, t.currency)}, ` +
        `31–60 ${m(t.d31_60, t.currency)}, 60+ ${m(t.d60_plus, t.currency)}; total ${m(t.total, t.currency)}`,
    );
  }
  if (a.invoices.length === 0) lines.push("  Nothing outstanding.");
  for (const invoice of a.invoices) lines.push(`  ${describeInvoice(invoice, data)}`);
  return lines.join("\n");
}

// ---------------------------------------------------------------------------
// Reference
// ---------------------------------------------------------------------------

export function buildReference(data: BooksData): Reference {
  return {
    book: data.book,
    today: todayOf(data),
    accounts: accountSummaries(data),
    categories: data.categories,
    counterparties: [...data.counterparties].sort((a, b) => a.name.localeCompare(b.name)),
  };
}

export function summarizeReference(r: Reference, data: BooksData): string {
  const m = moneyIn(data);
  const kinds = (kind: "income" | "expense") =>
    r.categories
      .filter((c) => c.kind === kind && !c.archived)
      .map((c) => `${c.name} (${c.id})`)
      .join(", ");
  return [
    `${r.book.name} (${r.book.legalName}), base currency ${r.book.baseCurrency}, today ${r.today}`,
    "Accounts: " +
      r.accounts
        .map((a) => `${a.name} (${a.id}, ${a.kind}, ${a.currency}) ${m(a.balance, a.currency)}${a.archived ? ", archived" : ""}`)
        .join("; "),
    `Income categories: ${kinds("income")}`,
    `Expense categories: ${kinds("expense")}`,
    "Clients: " + r.counterparties.filter((c) => c.kind === "client").map((c) => `${c.name} (${c.id})`).join(", "),
    "Vendors: " + r.counterparties.filter((c) => c.kind === "vendor").map((c) => `${c.name} (${c.id})`).join(", "),
  ].join("\n");
}
