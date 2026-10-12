/**
 * The books' arithmetic: balances, invoice totals and status, and the reports.
 * Pure functions over the dataset; nothing here mutates it. Reports are cash
 * basis and in the base currency (each transaction's `baseAmount`).
 */
import type {
  AgingBucket,
  BooksData,
  Category,
  CategoryKind,
  Invoice,
  InvoiceLine,
  InvoiceStatus,
  Transaction,
} from "../shared/books.ts";
import { roundMinor } from "../shared/money.ts";
import { addDays, daysBetween, monthLabel, monthOf, monthsBetween } from "../shared/period.ts";
import type {
  AccountSummary,
  AgingTotals,
  CashPoint,
  Cashflow,
  InvoiceSummary,
  LedgerFilters,
  MonthPoint,
  Pnl,
  PnlLine,
  Receivables,
  TransactionRow,
} from "../shared/schema.ts";

export const todayOf = (data: BooksData) => data.asOf ?? new Date().toISOString().slice(0, 10);

// ---------------------------------------------------------------------------
// Balances
// ---------------------------------------------------------------------------

/** What one transaction does to each account it touches: signed, in account currency and in base. */
export function accountEffects(t: Transaction): { accountId: string; amount: number; base: number }[] {
  if (t.direction === "in") return [{ accountId: t.accountId, amount: t.amount, base: t.baseAmount }];
  if (t.direction === "out") return [{ accountId: t.accountId, amount: -t.amount, base: -t.baseAmount }];
  return [
    { accountId: t.accountId, amount: -t.amount, base: -t.baseAmount },
    { accountId: t.transferAccountId!, amount: t.transferAmount ?? t.amount, base: t.baseAmount },
  ];
}

/** Balance of every account at the end of `upTo` (inclusive): opening balance plus transactions. */
export function accountBalances(data: BooksData, upTo?: string): Map<string, { balance: number; base: number }> {
  const balances = new Map(
    data.accounts.map((a) => [a.id, { balance: a.openingBalance, base: a.openingBalanceBase }]),
  );
  for (const t of data.transactions) {
    if (upTo && t.date > upTo) continue;
    for (const effect of accountEffects(t)) {
      const entry = balances.get(effect.accountId);
      if (!entry) continue;
      entry.balance += effect.amount;
      entry.base += effect.base;
    }
  }
  return balances;
}

export function cashOnHand(data: BooksData, upTo?: string): number {
  let total = 0;
  for (const { base } of accountBalances(data, upTo).values()) total += base;
  return total;
}

export function accountSummaries(data: BooksData, upTo?: string): AccountSummary[] {
  const balances = accountBalances(data, upTo);
  return data.accounts.map((a) => ({
    id: a.id,
    name: a.name,
    kind: a.kind,
    currency: a.currency,
    number: a.number,
    balance: balances.get(a.id)!.balance,
    balanceBase: balances.get(a.id)!.base,
    unreconciled: data.transactions.filter(
      (t) => !t.reconciled && (t.accountId === a.id || t.transferAccountId === a.id),
    ).length,
    archived: a.archived,
  }));
}

/** Daily total cash (base currency) over `from`..`to`. */
export function cashSeries(data: BooksData, from: string, to: string): CashPoint[] {
  let balance = cashOnHand(data, addDays(from, -1));
  const byDay = new Map<string, number>();
  for (const t of data.transactions) {
    if (t.date < from || t.date > to || t.direction === "transfer") continue;
    byDay.set(t.date, (byDay.get(t.date) ?? 0) + (t.direction === "in" ? t.baseAmount : -t.baseAmount));
  }
  const points: CashPoint[] = [];
  for (let day = from; day <= to; day = addDays(day, 1)) {
    balance += byDay.get(day) ?? 0;
    points.push({ date: day, balance });
  }
  return points;
}

// ---------------------------------------------------------------------------
// Profit and loss
// ---------------------------------------------------------------------------

/**
 * Which side of the P&L a transaction lands on, and with what sign. A refund
 * (money in on an expense category, out on an income one) reduces that side.
 * Uncategorized money follows its direction. Transfers are on neither side.
 */
export function plEffect(t: Transaction, category: Category | undefined): { side: CategoryKind; amount: number } | null {
  if (t.direction === "transfer") return null;
  const side: CategoryKind = category ? category.kind : t.direction === "in" ? "income" : "expense";
  const positive = side === "income" ? t.direction === "in" : t.direction === "out";
  return { side, amount: positive ? t.baseAmount : -t.baseAmount };
}

const inRange = (t: Transaction, from: string, to: string) => t.date >= from && t.date <= to;

export function profitAndLoss(data: BooksData, from: string, to: string, topVendorCount = 5): Pnl {
  const categories = new Map(data.categories.map((c) => [c.id, c]));
  const counterparties = new Map(data.counterparties.map((c) => [c.id, c]));
  const lines = { income: new Map<string | null, PnlLine>(), expense: new Map<string | null, PnlLine>() };
  const vendors = new Map<string | null, { name: string; amount: number; count: number }>();

  for (const t of data.transactions) {
    if (!inRange(t, from, to)) continue;
    const category = t.categoryId ? categories.get(t.categoryId) : undefined;
    const effect = plEffect(t, category);
    if (!effect) continue;
    const key = category?.id ?? null;
    const bucket = lines[effect.side];
    const line = bucket.get(key) ?? { categoryId: key, name: category?.name ?? "Uncategorized", amount: 0, count: 0 };
    line.amount += effect.amount;
    line.count += 1;
    bucket.set(key, line);
    if (effect.side === "expense") {
      const vendorKey = t.counterpartyId;
      const vendor = vendors.get(vendorKey) ?? {
        name: (vendorKey && counterparties.get(vendorKey)?.name) || "No counterparty",
        amount: 0,
        count: 0,
      };
      vendor.amount += effect.amount;
      vendor.count += 1;
      vendors.set(vendorKey, vendor);
    }
  }

  // Largest first, the uncategorized line last.
  const ordered = (bucket: Map<string | null, PnlLine>) =>
    [...bucket.values()].sort((a, b) => {
      if (a.categoryId === null) return 1;
      if (b.categoryId === null) return -1;
      return b.amount - a.amount;
    });
  const income = ordered(lines.income);
  const expenses = ordered(lines.expense);
  const totalIncome = income.reduce((sum, l) => sum + l.amount, 0);
  const totalExpenses = expenses.reduce((sum, l) => sum + l.amount, 0);
  return {
    from,
    to,
    currency: data.book.baseCurrency,
    income,
    expenses,
    totalIncome,
    totalExpenses,
    net: totalIncome - totalExpenses,
    topVendors: [...vendors.entries()]
      .map(([counterpartyId, v]) => ({ counterpartyId, ...v }))
      .sort((a, b) => b.amount - a.amount)
      .slice(0, topVendorCount),
  };
}

export function monthlyIncomeExpense(data: BooksData, from: string, to: string): MonthPoint[] {
  const categories = new Map(data.categories.map((c) => [c.id, c]));
  const months = new Map(
    monthsBetween(from, to).map((m) => [m, { month: m, label: monthLabel(m), income: 0, expenses: 0, net: 0 }]),
  );
  for (const t of data.transactions) {
    if (!inRange(t, from, to)) continue;
    const effect = plEffect(t, t.categoryId ? categories.get(t.categoryId) : undefined);
    const point = months.get(monthOf(t.date));
    if (!effect || !point) continue;
    if (effect.side === "income") point.income += effect.amount;
    else point.expenses += effect.amount;
  }
  return [...months.values()].map((p) => ({ ...p, net: p.income - p.expenses }));
}

// ---------------------------------------------------------------------------
// Cash flow
// ---------------------------------------------------------------------------

export function cashflow(data: BooksData, from: string, to: string): Cashflow {
  const before = addDays(from, -1);
  const opening = cashOnHand(data, before);
  let inflows = 0;
  let outflows = 0;
  const months = new Map(
    monthsBetween(from, to).map((m) => [m, { month: m, label: monthLabel(m), inflows: 0, outflows: 0, net: 0, closing: 0 }]),
  );
  for (const t of data.transactions) {
    if (!inRange(t, from, to) || t.direction === "transfer") continue;
    const point = months.get(monthOf(t.date))!;
    if (t.direction === "in") {
      inflows += t.baseAmount;
      point.inflows += t.baseAmount;
    } else {
      outflows += t.baseAmount;
      point.outflows += t.baseAmount;
    }
  }
  let running = opening;
  const monthRows = [...months.values()].map((p) => {
    running += p.inflows - p.outflows;
    return { ...p, net: p.inflows - p.outflows, closing: running };
  });
  const openingBalances = accountBalances(data, before);
  const closingBalances = accountBalances(data, to);
  return {
    from,
    to,
    currency: data.book.baseCurrency,
    opening,
    inflows,
    outflows,
    closing: opening + inflows - outflows,
    months: monthRows,
    accounts: data.accounts.map((a) => ({
      id: a.id,
      name: a.name,
      currency: a.currency,
      opening: openingBalances.get(a.id)!.balance,
      closing: closingBalances.get(a.id)!.balance,
      openingBase: openingBalances.get(a.id)!.base,
      closingBase: closingBalances.get(a.id)!.base,
    })),
    series: cashSeries(data, from, to),
  };
}

// ---------------------------------------------------------------------------
// Invoices
// ---------------------------------------------------------------------------

export function lineAmounts(line: InvoiceLine) {
  const net = roundMinor(line.quantity * line.unitPrice);
  const vat = line.vatRate ? roundMinor((net * line.vatRate) / 100) : 0;
  return { net, vat, total: net + vat };
}

/** VAT is computed and rounded per line, then summed. */
export function invoiceTotals(lines: InvoiceLine[]) {
  const computed = lines.map((line) => ({ ...line, ...lineAmounts(line) }));
  const breakdown = new Map<number | null, { rate: number | null; net: number; vat: number }>();
  for (const line of computed) {
    const rate = line.vatRate || null;
    const entry = breakdown.get(rate) ?? { rate, net: 0, vat: 0 };
    entry.net += line.net;
    entry.vat += line.vat;
    breakdown.set(rate, entry);
  }
  const subtotal = computed.reduce((sum, l) => sum + l.net, 0);
  const vatTotal = computed.reduce((sum, l) => sum + l.vat, 0);
  return { lines: computed, subtotal, vatTotal, total: subtotal + vatTotal, vatBreakdown: [...breakdown.values()] };
}

export function deriveInvoiceStatus(input: {
  sent: boolean;
  voided: boolean;
  total: number;
  paid: number;
  dueDate: string;
  today: string;
}): InvoiceStatus {
  if (input.voided) return "void";
  if (input.paid >= input.total && input.total > 0) return "paid";
  if (!input.sent) return "draft";
  if (input.today > input.dueDate) return "overdue";
  return input.paid > 0 ? "partially_paid" : "sent";
}

export const invoicePayments = (data: BooksData, invoiceId: string) =>
  data.transactions.filter((t) => t.invoiceId === invoiceId).sort((a, b) => a.date.localeCompare(b.date));

/** Money received against an invoice: incoming transactions linked to it, net of any refunds. */
export function amountPaid(data: BooksData, invoiceId: string): number {
  return invoicePayments(data, invoiceId).reduce((sum, t) => sum + (t.direction === "in" ? t.amount : -t.amount), 0);
}

export function invoiceSummary(data: BooksData, invoice: Invoice, today: string): InvoiceSummary {
  const { total } = invoiceTotals(invoice.lines);
  const paid = amountPaid(data, invoice.id);
  const status = deriveInvoiceStatus({
    sent: invoice.sentAt !== null,
    voided: invoice.voidedAt !== null,
    total,
    paid,
    dueDate: invoice.dueDate,
    today,
  });
  const balanceDue = status === "void" ? 0 : Math.max(0, total - paid);
  const client = data.counterparties.find((c) => c.id === invoice.counterpartyId);
  return {
    id: invoice.id,
    number: invoice.number,
    client: { id: invoice.counterpartyId, name: client?.name ?? invoice.counterpartyId },
    issueDate: invoice.issueDate,
    dueDate: invoice.dueDate,
    currency: invoice.currency,
    total,
    amountPaid: paid,
    balanceDue,
    status,
    daysOverdue: status === "overdue" ? daysBetween(invoice.dueDate, today) : 0,
  };
}

export function agingBucket(daysOverdue: number): AgingBucket {
  if (daysOverdue <= 0) return "current";
  if (daysOverdue <= 30) return "d1_30";
  if (daysOverdue <= 60) return "d31_60";
  return "d60_plus";
}

const OPEN: ReadonlySet<InvoiceStatus> = new Set(["sent", "partially_paid", "overdue"]);

/** Open invoices (sent, not fully paid, not void) by how far past due they are. */
export function receivablesAging(data: BooksData, today: string): Receivables {
  const invoices = data.invoices
    .map((invoice) => invoiceSummary(data, invoice, today))
    .filter((s) => OPEN.has(s.status) && s.balanceDue > 0)
    .map((s) => ({ ...s, bucket: agingBucket(s.daysOverdue) }))
    .sort((a, b) => b.daysOverdue - a.daysOverdue || a.dueDate.localeCompare(b.dueDate));
  const totals = new Map<string, AgingTotals>();
  for (const invoice of invoices) {
    const entry = totals.get(invoice.currency) ?? {
      currency: invoice.currency,
      current: 0,
      d1_30: 0,
      d31_60: 0,
      d60_plus: 0,
      total: 0,
    };
    entry[invoice.bucket] += invoice.balanceDue;
    entry.total += invoice.balanceDue;
    totals.set(invoice.currency, entry);
  }
  return { asOf: today, totals: [...totals.values()], invoices };
}

// ---------------------------------------------------------------------------
// Ledger rows
// ---------------------------------------------------------------------------

export function transactionRow(data: BooksData, t: Transaction): TransactionRow {
  const account = (id: string) => {
    const a = data.accounts.find((x) => x.id === id);
    return { id, name: a?.name ?? id, currency: a?.currency ?? data.book.baseCurrency };
  };
  const counterparty = t.counterpartyId ? data.counterparties.find((c) => c.id === t.counterpartyId) : undefined;
  const category = t.categoryId ? data.categories.find((c) => c.id === t.categoryId) : undefined;
  const invoice = t.invoiceId ? data.invoices.find((i) => i.id === t.invoiceId) : undefined;
  const from = account(t.accountId);
  return {
    id: t.id,
    date: t.date,
    account: from,
    direction: t.direction,
    amount: t.amount,
    currency: from.currency,
    baseAmount: t.baseAmount,
    transferAccount: t.transferAccountId ? account(t.transferAccountId) : null,
    transferAmount: t.transferAmount,
    counterparty: counterparty ? { id: counterparty.id, name: counterparty.name } : null,
    category: category ? { id: category.id, name: category.name, kind: category.kind } : null,
    description: t.description,
    bankMemo: t.bankMemo,
    invoice: invoice ? { id: invoice.id, number: invoice.number } : null,
    reconciled: t.reconciled,
    attachments: t.attachments,
    source: t.source,
  };
}

/** Transactions matching every given filter, newest first. */
export function filterTransactions(data: BooksData, filters: LedgerFilters): Transaction[] {
  const text = filters.text?.trim().toLowerCase();
  const names = text ? new Map(data.counterparties.map((c) => [c.id, c.name.toLowerCase()])) : null;
  return data.transactions
    .filter((t) => {
      if (filters.from && t.date < filters.from) return false;
      if (filters.to && t.date > filters.to) return false;
      if (filters.account && t.accountId !== filters.account && t.transferAccountId !== filters.account) return false;
      if (filters.uncategorized && (t.categoryId !== null || t.direction === "transfer")) return false;
      if (filters.category && t.categoryId !== filters.category) return false;
      if (filters.counterparty && t.counterpartyId !== filters.counterparty) return false;
      if (filters.direction && t.direction !== filters.direction) return false;
      if (filters.reconciled !== null && t.reconciled !== filters.reconciled) return false;
      if (text && names) {
        const haystack = `${t.description} ${t.bankMemo ?? ""} ${t.counterpartyId ? names.get(t.counterpartyId) ?? "" : ""}`.toLowerCase();
        if (!haystack.includes(text)) return false;
      }
      return true;
    })
    .sort((a, b) => b.date.localeCompare(a.date) || b.id.localeCompare(a.id));
}

export function totalsOf(transactions: Transaction[]) {
  let incoming = 0;
  let outgoing = 0;
  for (const t of transactions) {
    if (t.direction === "in") incoming += t.baseAmount;
    if (t.direction === "out") outgoing += t.baseAmount;
  }
  return { in: incoming, out: outgoing, net: incoming - outgoing };
}

export const uncategorized = (data: BooksData) =>
  data.transactions.filter((t) => t.categoryId === null && t.direction !== "transfer");
