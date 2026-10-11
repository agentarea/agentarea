import { z } from "zod";
import {
  ACCOUNT_KINDS,
  AGING_BUCKETS,
  CATEGORY_KINDS,
  COUNTERPARTY_KINDS,
  DIRECTIONS,
  INVOICE_STATUSES,
  PERIOD_KINDS,
  TRANSACTION_SOURCES,
} from "./books.ts";

// Every money field is an integer in minor units (kopecks, cents) of the
// currency named beside it, or of the book's base currency for totals.
const money = z.number().int();
const date = z.string().describe("YYYY-MM-DD");
const ref = z.object({ id: z.string(), name: z.string() });

export const bookSchema = z.object({
  name: z.string(),
  legalName: z.string(),
  taxId: z.string().nullable(),
  address: z.string().nullable(),
  email: z.string().nullable(),
  bankDetails: z.string().nullable(),
  baseCurrency: z.string(),
  locale: z.string(),
});

export const periodSchema = z.object({
  kind: z.enum(PERIOD_KINDS),
  from: date,
  to: date,
  label: z.string(),
});

export const accountSummarySchema = z.object({
  id: z.string(),
  name: z.string(),
  kind: z.enum(ACCOUNT_KINDS),
  currency: z.string(),
  number: z.string().nullable(),
  balance: money.describe("In the account's currency"),
  balanceBase: money.describe("In the base currency"),
  unreconciled: z.number().int(),
  archived: z.boolean(),
});

export const categorySchema = z.object({
  id: z.string(),
  name: z.string(),
  kind: z.enum(CATEGORY_KINDS),
  archived: z.boolean(),
});

export const counterpartySchema = z.object({
  id: z.string(),
  name: z.string(),
  kind: z.enum(COUNTERPARTY_KINDS),
  taxId: z.string().nullable(),
  email: z.string().nullable(),
});

// ---------------------------------------------------------------------------
// Reports
// ---------------------------------------------------------------------------

export const pnlLineSchema = z.object({
  /** Null for the uncategorized line. */
  categoryId: z.string().nullable(),
  name: z.string(),
  amount: money,
  count: z.number().int(),
});

export const vendorSpendSchema = z.object({
  counterpartyId: z.string().nullable(),
  name: z.string(),
  amount: money,
  count: z.number().int(),
});

export const pnlSchema = z.object({
  from: date,
  to: date,
  currency: z.string(),
  income: z.array(pnlLineSchema),
  expenses: z.array(pnlLineSchema),
  totalIncome: money,
  totalExpenses: money,
  net: money,
  topVendors: z.array(vendorSpendSchema),
});

export const monthPointSchema = z.object({
  month: z.string().describe("YYYY-MM"),
  label: z.string(),
  income: money,
  expenses: money,
  net: money,
});

export const cashPointSchema = z.object({ date, balance: money });

export const cashflowSchema = z.object({
  from: date,
  to: date,
  currency: z.string(),
  opening: money,
  inflows: money,
  outflows: money,
  closing: money,
  months: z.array(
    z.object({ month: z.string(), label: z.string(), inflows: money, outflows: money, net: money, closing: money }),
  ),
  accounts: z.array(
    z.object({
      id: z.string(),
      name: z.string(),
      currency: z.string(),
      opening: money,
      closing: money,
      openingBase: money,
      closingBase: money,
    }),
  ),
  series: z.array(cashPointSchema),
});

export const invoiceSummarySchema = z.object({
  id: z.string(),
  number: z.string(),
  client: ref,
  issueDate: date,
  dueDate: date,
  currency: z.string(),
  total: money,
  amountPaid: money,
  balanceDue: money,
  status: z.enum(INVOICE_STATUSES),
  /** Days past the due date with a balance left; 0 otherwise. */
  daysOverdue: z.number().int(),
});

export const agingTotalsSchema = z.object({
  currency: z.string(),
  current: money,
  d1_30: money,
  d31_60: money,
  d60_plus: money,
  total: money,
});

export const receivablesSchema = z.object({
  asOf: date,
  totals: z.array(agingTotalsSchema),
  invoices: z.array(invoiceSummarySchema.extend({ bucket: z.enum(AGING_BUCKETS) })),
});

export const reportSchema = z.object({
  report: z.enum(["pnl", "cashflow", "receivables"]),
  book: bookSchema,
  period: periodSchema.nullable(),
  pnl: pnlSchema.optional(),
  cashflow: cashflowSchema.optional(),
  receivables: receivablesSchema.optional(),
});

// ---------------------------------------------------------------------------
// Transactions
// ---------------------------------------------------------------------------

const accountRef = z.object({ id: z.string(), name: z.string(), currency: z.string() });

export const transactionRowSchema = z.object({
  id: z.string(),
  date,
  account: accountRef,
  direction: z.enum(DIRECTIONS),
  amount: money.describe("Positive, in the account's currency"),
  currency: z.string(),
  baseAmount: money,
  transferAccount: accountRef.nullable(),
  transferAmount: money.nullable(),
  counterparty: ref.nullable(),
  category: z.object({ id: z.string(), name: z.string(), kind: z.enum(CATEGORY_KINDS) }).nullable(),
  description: z.string(),
  bankMemo: z.string().nullable(),
  invoice: z.object({ id: z.string(), number: z.string() }).nullable(),
  reconciled: z.boolean(),
  attachments: z.array(z.string()),
  source: z.enum(TRANSACTION_SOURCES),
});

export const ledgerFiltersSchema = z.object({
  from: date.nullable(),
  to: date.nullable(),
  account: z.string().nullable(),
  category: z.string().nullable(),
  uncategorized: z.boolean(),
  counterparty: z.string().nullable(),
  direction: z.enum(DIRECTIONS).nullable(),
  reconciled: z.boolean().nullable(),
  text: z.string().nullable(),
});

export const transactionListSchema = z.object({
  today: date,
  baseCurrency: z.string(),
  filters: ledgerFiltersSchema,
  /** Matching transactions before paging. */
  total: z.number().int(),
  offset: z.number().int(),
  limit: z.number().int(),
  /** Over every matching transaction, in the base currency; transfers excluded. */
  totals: z.object({ in: money, out: money, net: money }),
  rows: z.array(transactionRowSchema),
});

export const ledgerSchema = transactionListSchema.extend({
  book: bookSchema,
  uncategorizedCount: z.number().int(),
  accounts: z.array(accountRef.extend({ kind: z.enum(ACCOUNT_KINDS), archived: z.boolean() })),
  categories: z.array(categorySchema),
  counterparties: z.array(z.object({ id: z.string(), name: z.string(), kind: z.enum(COUNTERPARTY_KINDS) })),
});

export const transactionResultSchema = z.object({ transaction: transactionRowSchema });

export const deletedSchema = z.object({ id: z.string(), deleted: z.literal(true) });

export const reconciledResultSchema = z.object({
  updated: z.number().int(),
  ids: z.array(z.string()),
  reconciled: z.boolean(),
});

export const categorizeResultSchema = z.object({
  updated: z.number().int(),
  category: ref.nullable(),
  counterparty: ref.nullable(),
  transactions: z.array(transactionRowSchema),
  remainingUncategorized: z.number().int(),
});

export const importResultSchema = z.object({
  account: ref,
  dryRun: z.boolean(),
  created: z.number().int(),
  skipped: z.number().int(),
  failed: z.number().int(),
  duplicates: z.array(z.object({ line: z.number().int(), date, amount: money, description: z.string() })),
  errors: z.array(z.object({ line: z.number().int(), message: z.string() })),
  /** What was created, or with dryRun what would be. */
  transactions: z.array(transactionRowSchema),
});

// ---------------------------------------------------------------------------
// Invoices
// ---------------------------------------------------------------------------

export const invoiceDetailSchema = invoiceSummarySchema.extend({
  client: ref.extend({ taxId: z.string().nullable(), email: z.string().nullable() }),
  lines: z.array(
    z.object({
      description: z.string(),
      quantity: z.number(),
      unitPrice: money,
      vatRate: z.number().nullable(),
      net: money,
      vat: money,
      total: money,
    }),
  ),
  subtotal: money,
  vatTotal: money,
  vatBreakdown: z.array(z.object({ rate: z.number().nullable(), net: money, vat: money })),
  notes: z.string().nullable(),
  category: ref.nullable(),
  sentAt: z.string().nullable(),
  voidedAt: z.string().nullable(),
});

export const paymentSchema = z.object({
  transactionId: z.string(),
  date,
  amount: money,
  account: ref,
  reconciled: z.boolean(),
});

export const invoiceViewSchema = z.object({
  book: bookSchema,
  today: date,
  invoice: invoiceDetailSchema,
  payments: z.array(paymentSchema),
  /** Accounts that can receive a payment in the invoice currency. */
  accounts: z.array(accountRef),
});

export const invoiceListSchema = z.object({
  today: date,
  invoices: z.array(invoiceSummarySchema),
  outstanding: z.array(z.object({ currency: z.string(), amount: money })),
});

export const paymentResultSchema = z.object({
  invoice: invoiceSummarySchema,
  payment: transactionRowSchema,
});

// ---------------------------------------------------------------------------
// Overview
// ---------------------------------------------------------------------------

export const overviewSchema = z.object({
  book: bookSchema,
  today: date,
  period: periodSchema,
  previous: periodSchema.extend({ income: money, expenses: money, net: money }),
  kpis: z.object({
    /** Across all accounts, in the base currency, at the period end (or today if earlier). */
    cash: money,
    cashAsOf: date,
    income: money,
    expenses: money,
    net: money,
    receivables: money,
    receivablesCount: z.number().int(),
    overdue: money,
    overdueCount: z.number().int(),
  }),
  /** Twelve months ending with the period's last month. */
  months: z.array(monthPointSchema.extend({ inPeriod: z.boolean() })),
  pnl: pnlSchema,
  accounts: z.array(accountSummarySchema),
  cashSeries: z.array(cashPointSchema),
  uncategorized: z.object({ count: z.number().int(), oldest: date.nullable() }),
  overdueInvoices: z.array(invoiceSummarySchema),
  aging: agingTotalsSchema,
});

export const referenceSchema = z.object({
  book: bookSchema,
  today: date,
  accounts: z.array(accountSummarySchema),
  categories: z.array(categorySchema),
  counterparties: z.array(counterpartySchema),
});

export type BookInfo = z.infer<typeof bookSchema>;
export type PeriodInfo = z.infer<typeof periodSchema>;
export type AccountSummary = z.infer<typeof accountSummarySchema>;
export type PnlLine = z.infer<typeof pnlLineSchema>;
export type Pnl = z.infer<typeof pnlSchema>;
export type MonthPoint = z.infer<typeof monthPointSchema>;
export type CashPoint = z.infer<typeof cashPointSchema>;
export type Cashflow = z.infer<typeof cashflowSchema>;
export type InvoiceSummary = z.infer<typeof invoiceSummarySchema>;
export type AgingTotals = z.infer<typeof agingTotalsSchema>;
export type Receivables = z.infer<typeof receivablesSchema>;
export type Report = z.infer<typeof reportSchema>;
export type TransactionRow = z.infer<typeof transactionRowSchema>;
export type LedgerFilters = z.infer<typeof ledgerFiltersSchema>;
export type TransactionList = z.infer<typeof transactionListSchema>;
export type Ledger = z.infer<typeof ledgerSchema>;
export type CategorizeResult = z.infer<typeof categorizeResultSchema>;
export type ImportResult = z.infer<typeof importResultSchema>;
export type InvoiceDetail = z.infer<typeof invoiceDetailSchema>;
export type Payment = z.infer<typeof paymentSchema>;
export type InvoiceView = z.infer<typeof invoiceViewSchema>;
export type InvoiceList = z.infer<typeof invoiceListSchema>;
export type PaymentResult = z.infer<typeof paymentResultSchema>;
export type Overview = z.infer<typeof overviewSchema>;
export type Reference = z.infer<typeof referenceSchema>;
