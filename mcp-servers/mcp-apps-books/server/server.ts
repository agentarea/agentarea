import {
  registerAppResource,
  registerAppTool,
  RESOURCE_MIME_TYPE,
} from "@modelcontextprotocol/ext-apps/server";
import type { AppStore } from "@kit/store/store.ts";
import { McpServer, type ReadResourceResult } from "@modelcontextprotocol/server";
import fs from "node:fs/promises";
import path from "node:path";
import { z } from "zod";
import {
  CATEGORY_KINDS,
  COUNTERPARTY_KINDS,
  DIRECTIONS,
  INVOICE_STATUSES,
  PERIOD_KINDS,
} from "../shared/books.ts";
import { formatMoney } from "../shared/money.ts";
import { resolvePeriod } from "../shared/period.ts";
import {
  categorizeResultSchema,
  categorySchema,
  counterpartySchema,
  deletedSchema,
  importResultSchema,
  invoiceListSchema,
  invoiceViewSchema,
  ledgerSchema,
  overviewSchema,
  paymentResultSchema,
  reconciledResultSchema,
  referenceSchema,
  reportSchema,
  transactionListSchema,
  transactionResultSchema,
  type LedgerFilters,
} from "../shared/schema.ts";
import { invoiceSummary, transactionRow, uncategorized } from "./ledger.ts";
import { DATE_FORMATS } from "./statement.ts";
import { BooksStore } from "./store.ts";
import {
  buildInvoiceList,
  buildInvoiceView,
  buildLedger,
  buildOverview,
  buildReference,
  buildReport,
  buildTransactionList,
  describeInvoice,
  describeRow,
  periodOf,
  summarizeInvoice,
  summarizeOverview,
  summarizeReference,
  summarizeReport,
  summarizeTransactions,
} from "./views.ts";

export const OVERVIEW_URI = "ui://books/overview.html";
export const LEDGER_URI = "ui://books/transactions.html";
export const INVOICE_URI = "ui://books/invoice.html";

/** Built views, one single-file HTML each, inside `appDir`. */
const VIEWS = [
  { uri: OVERVIEW_URI, name: "Books overview", file: "overview.html", description: "Cash, profit and loss, receivables" },
  { uri: LEDGER_URI, name: "Transactions", file: "transactions.html", description: "The ledger: categorize, reconcile, add" },
  { uri: INVOICE_URI, name: "Invoice", file: "invoice.html", description: "One invoice: send, record payment, void" },
] as const;
export const VIEW_FILES = VIEWS.map((view) => view.file);

const READ = { readOnlyHint: true, openWorldHint: false } as const;
const write = (idempotentHint: boolean, destructiveHint = false) =>
  ({ readOnlyHint: false, idempotentHint, destructiveHint, openWorldHint: false }) as const;

const amount = z
  .union([z.number(), z.string()])
  .describe('Major units as written, e.g. 1250.5 or "1 250,50" (not kopecks/cents)');
const day = z.string().describe("YYYY-MM-DD");

const periodFields = {
  period: z
    .enum(PERIOD_KINDS)
    .optional()
    .describe("Calendar month (default), quarter or year holding `date`, or custom with from/to"),
  date: day.optional().describe("Any day inside the wanted month/quarter/year, YYYY-MM-DD; default today"),
  from: day.optional().describe("Custom period start, YYYY-MM-DD"),
  to: day.optional().describe("Custom period end, YYYY-MM-DD"),
};

const filterFields = {
  period: z
    .enum(PERIOD_KINDS)
    .optional()
    .describe("Limit to the month/quarter/year holding `date`; or custom with from/to. Omit for all dates"),
  date: day.optional().describe("Any day inside the wanted period; default today"),
  from: day.optional().describe("On or after, YYYY-MM-DD"),
  to: day.optional().describe("On or before, YYYY-MM-DD"),
  account: z.string().optional().describe("Account id or name; matches either side of a transfer"),
  category: z.string().optional().describe('Category id or name, or "uncategorized"'),
  uncategorized: z.boolean().optional().describe("Only income/expense lines with no category yet (to review)"),
  counterparty: z.string().optional().describe("Counterparty id or name"),
  direction: z.enum(DIRECTIONS).optional(),
  reconciled: z.boolean().optional().describe("true for reconciled only, false for unreconciled only"),
  text: z.string().optional().describe("Search in description, bank memo and counterparty name"),
  offset: z.number().int().min(0).optional(),
};

type FilterInput = {
  period?: (typeof PERIOD_KINDS)[number];
  date?: string;
  from?: string;
  to?: string;
  account?: string;
  category?: string;
  uncategorized?: boolean;
  counterparty?: string;
  direction?: (typeof DIRECTIONS)[number];
  reconciled?: boolean;
  text?: string;
};

function resolveFilters(store: BooksStore, input: FilterInput): LedgerFilters {
  let from = input.from ?? null;
  let to = input.to ?? null;
  if (input.period) {
    const period = resolvePeriod(input.period, input.date ?? store.today, input.from, input.to);
    from = period.from;
    to = period.to;
  }
  const wantsUncategorized = input.uncategorized === true || input.category?.trim().toLowerCase() === "uncategorized";
  return {
    from,
    to,
    account: input.account ? store.account(input.account).id : null,
    category: input.category && !wantsUncategorized ? store.category(input.category).id : null,
    uncategorized: wantsUncategorized,
    counterparty: input.counterparty ? store.counterparty(input.counterparty).id : null,
    direction: input.direction ?? null,
    reconciled: input.reconciled ?? null,
    text: input.text?.trim() || null,
  };
}

const lineInput = z.object({
  description: z.string(),
  quantity: z.number().positive().describe("e.g. 1, 40 (hours), 1.5"),
  unit_price: amount.describe("Per unit, net of VAT, major units"),
  vat_rate: z.number().min(0).max(100).nullable().optional().describe("VAT percent, e.g. 22; null or omitted for no VAT"),
});
const toLines = (lines: z.infer<typeof lineInput>[]) =>
  lines.map((l) => ({ description: l.description, quantity: l.quantity, unitPrice: l.unit_price, vatRate: l.vat_rate ?? null }));

const column = z.union([z.string(), z.number().int().min(0)]).describe("Header name, or 0-based column index");

/**
 * The app is the view resources plus their tools. The data is not part of
 * it: it lives in `app`, the instance's store; every tool call is one read or
 * one transaction there. `current` is the books as of this request, for the
 * accounts the tool descriptions name.
 */
export function createServer(app: AppStore, appDir: string, current: BooksStore): McpServer {
  const server = new McpServer({ name: "Books MCP App", version: "0.1.0" });
  const m = (minor: number, currency = current.base) => formatMoney(minor, currency, current.data.book.locale);
  const read = <T>(fn: (store: BooksStore) => T) => app.read((db) => fn(BooksStore.load(db)));
  const change = <T>(fn: (store: BooksStore) => T) =>
    app.transact((db) => {
      const store = BooksStore.load(db);
      const result = fn(store);
      store.save(db);
      return result;
    });
  const accountNames = current.data.accounts
    .filter((a) => !a.archived)
    .map((a) => `${a.name} (${a.id}, ${a.currency})`)
    .join(", ");
  const reply = <T extends Record<string, unknown>>(text: string, structuredContent: T) => ({
    content: [{ type: "text" as const, text }],
    structuredContent,
  });

  // -------------------------------------------------------------------------
  // Views
  // -------------------------------------------------------------------------

  registerAppTool(
    server,
    "show_books_overview",
    {
      title: "Show books overview",
      description:
        "Open the bookkeeping overview for a period: cash on hand, income, expenses, net profit, receivables and " +
        "overdue invoices, income vs expenses by month, P&L by category, account balances and how many " +
        "transactions still need a category.",
      inputSchema: z.object(periodFields),
      outputSchema: overviewSchema,
      annotations: READ,
      _meta: { ui: { resourceUri: OVERVIEW_URI } },
    },
    async ({ period, date, from, to }) =>
      read((store) => {
        const data = store.data;
        const overview = buildOverview(data, periodOf(data, period, date, from, to));
        return reply(summarizeOverview(overview, data), overview);
      }),
  );

  registerAppTool(
    server,
    "show_transactions",
    {
      title: "Show transactions",
      description:
        "Open the ledger: every transaction with account, counterparty, memo, category, amount and reconciled " +
        "state, filterable; the user can categorize, reconcile and add transactions there.",
      inputSchema: z.object({
        ...filterFields,
        limit: z.number().int().min(1).max(1000).optional().describe("Rows to return, default 200"),
      }),
      outputSchema: ledgerSchema,
      annotations: READ,
      _meta: { ui: { resourceUri: LEDGER_URI } },
    },
    async (input) =>
      read((store) => {
        const data = store.data;
        const ledger = buildLedger(data, resolveFilters(store, input), input.offset ?? 0, input.limit ?? 200);
        return reply(summarizeTransactions(ledger, data, 25), ledger);
      }),
  );

  registerAppTool(
    server,
    "show_invoice",
    {
      title: "Show invoice",
      description: "Open one invoice: lines, VAT, totals, status, payment history; send it, record a payment or void it.",
      inputSchema: z.object({ number: z.string().describe('Invoice number, e.g. "INV-0007"') }),
      outputSchema: invoiceViewSchema,
      annotations: READ,
      _meta: { ui: { resourceUri: INVOICE_URI } },
    },
    async ({ number }) =>
      read((store) => {
        const data = store.data;
        const view = buildInvoiceView(data, store.invoice(number));
        return reply(summarizeInvoice(view, data), view);
      }),
  );

  // -------------------------------------------------------------------------
  // Reading the books
  // -------------------------------------------------------------------------

  server.registerTool(
    "get_books_reference",
    {
      title: "Get books reference",
      description:
        "Accounts with balances, income and expense categories, clients and vendors, with their ids. " +
        "Every other tool also accepts names where it asks for an account, category or counterparty.",
      inputSchema: z.object({}),
      outputSchema: referenceSchema,
      annotations: READ,
    },
    async () =>
      read((store) => {
        const data = store.data;
        const reference = buildReference(data);
        return reply(summarizeReference(reference, data), reference);
      }),
  );

  server.registerTool(
    "list_transactions",
    {
      title: "List transactions",
      description:
        "Find transactions, newest first, with totals over everything that matches. Use uncategorized=true for " +
        "the review queue. Amounts in the result are integers in minor units (kopecks/cents).",
      inputSchema: z.object({
        ...filterFields,
        limit: z.number().int().min(1).max(500).optional().describe("Rows to return, default 50"),
      }),
      outputSchema: transactionListSchema,
      annotations: READ,
    },
    async (input) =>
      read((store) => {
        const data = store.data;
        const list = buildTransactionList(data, resolveFilters(store, input), input.offset ?? 0, input.limit ?? 50);
        return reply(summarizeTransactions(list, data), list);
      }),
  );

  server.registerTool(
    "list_invoices",
    {
      title: "List invoices",
      description: "Invoices with total, paid, balance due and status, newest number first.",
      inputSchema: z.object({
        status: z.array(z.enum(INVOICE_STATUSES)).optional().describe("Only these statuses; omit for all"),
        client: z.string().optional().describe("Client id or name"),
      }),
      outputSchema: invoiceListSchema,
      annotations: READ,
    },
    async ({ status, client }) =>
      read((store) => {
        const data = store.data;
        const list = buildInvoiceList(data, status ?? null, client ? store.counterparty(client).id : null);
        const outstanding = list.outstanding.map((o) => m(o.amount, o.currency)).join(" + ") || m(0);
        const text = [
          `${list.invoices.length} invoices; outstanding ${outstanding}`,
          ...list.invoices.map((s) => describeInvoice(s, data)),
        ].join("\n");
        return reply(text, list);
      }),
  );

  server.registerTool(
    "get_report",
    {
      title: "Get report",
      description:
        "pnl: profit and loss by category for the period, with top vendors. cashflow: opening and closing cash, " +
        "money in and out by month and per account. receivables: open invoices by age (current, 1–30, 31–60, " +
        "60+ days past due) as of today. Cash basis, in the base currency.",
      inputSchema: z.object({ report: z.enum(["pnl", "cashflow", "receivables"]), ...periodFields }),
      outputSchema: reportSchema,
      annotations: READ,
    },
    async ({ report, period, date, from, to }) =>
      read((store) => {
        const data = store.data;
        const result = buildReport(data, report, periodOf(data, period, date, from, to));
        return reply(summarizeReport(result, data), result);
      }),
  );

  // -------------------------------------------------------------------------
  // Transactions
  // -------------------------------------------------------------------------

  server.registerTool(
    "record_transaction",
    {
      title: "Record transaction",
      description:
        `Add one transaction to an account. Accounts: ${accountNames}. Money in or out of the business is ` +
        "\"in\"/\"out\" and takes a category; moving money between the book's own accounts is \"transfer\" with " +
        "to_account and never a category. Leave category out to queue it for review.",
      inputSchema: z.object({
        date: day.optional().describe("Default today"),
        account: z.string().describe("Account id or name"),
        direction: z.enum(DIRECTIONS),
        amount: amount.describe("Positive, in the account's currency, major units"),
        base_amount: amount.optional().describe("Value in the base currency; required when the account is in another currency"),
        to_account: z.string().optional().describe("Transfers: the receiving account"),
        to_amount: amount.optional().describe("Transfers between currencies: what the receiving account got"),
        counterparty: z.string().optional().describe("Client or vendor id or name"),
        category: z.string().optional().describe("Category id or name"),
        description: z.string().describe("What it was for, or the bank memo"),
        attachments: z.array(z.string()).optional().describe("File names or URLs of receipts"),
        reconciled: z.boolean().optional(),
      }),
      outputSchema: transactionResultSchema,
      annotations: write(false),
    },
    async (input) =>
      change((store) => {
        const data = store.data;
        const t = store.recordTransaction({
          date: input.date,
          account: input.account,
          direction: input.direction,
          amount: input.amount,
          baseAmount: input.base_amount,
          toAccount: input.to_account,
          toAmount: input.to_amount,
          counterparty: input.counterparty,
          category: input.category,
          description: input.description,
          attachments: input.attachments,
          reconciled: input.reconciled,
        });
        const row = transactionRow(data, t);
        return reply(`Recorded ${describeRow(row, data)}`, { transaction: row });
      }),
  );

  server.registerTool(
    "update_transaction",
    {
      title: "Update transaction",
      description:
        "Change one transaction. Only the fields given change; pass null for counterparty or category to clear it. " +
        "A reconciled transaction's date, account or amount change only together with reconciled=false.",
      inputSchema: z.object({
        id: z.string().describe('Transaction id, e.g. "tx_00412"'),
        date: day.optional(),
        account: z.string().optional(),
        direction: z.enum(DIRECTIONS).optional(),
        amount: amount.optional(),
        base_amount: amount.optional(),
        to_account: z.string().optional(),
        to_amount: amount.optional(),
        counterparty: z.string().nullable().optional(),
        category: z.string().nullable().optional(),
        description: z.string().optional(),
        reconciled: z.boolean().optional(),
        attachments: z.array(z.string()).optional().describe("Replaces the list"),
        add_attachments: z.array(z.string()).optional().describe("Appends to the list"),
      }),
      outputSchema: transactionResultSchema,
      annotations: write(true),
    },
    async (input) =>
      change((store) => {
        const data = store.data;
        const t = store.updateTransaction(input.id, {
          date: input.date,
          account: input.account,
          direction: input.direction,
          amount: input.amount,
          baseAmount: input.base_amount,
          toAccount: input.to_account,
          toAmount: input.to_amount,
          counterparty: input.counterparty,
          category: input.category,
          description: input.description,
          reconciled: input.reconciled,
          attachments: input.attachments,
          addAttachments: input.add_attachments,
        });
        const row = transactionRow(data, t);
        return reply(`Updated ${describeRow(row, data)}`, { transaction: row });
      }),
  );

  server.registerTool(
    "delete_transaction",
    {
      title: "Delete transaction",
      description: "Remove a transaction entered by mistake or twice. Reconciled ones must be unreconciled first.",
      inputSchema: z.object({ id: z.string() }),
      outputSchema: deletedSchema,
      annotations: write(false, true),
    },
    async ({ id }) =>
      change((store) => {
        const data = store.data;
        const row = transactionRow(data, store.transaction(id));
        store.deleteTransaction(id);
        return reply(`Deleted ${describeRow(row, data)}`, { id, deleted: true as const });
      }),
  );

  server.registerTool(
    "set_reconciled",
    {
      title: "Set reconciled",
      description: "Mark transactions as matched against the bank statement (or undo that).",
      inputSchema: z.object({
        ids: z.array(z.string()).min(1),
        reconciled: z.boolean(),
      }),
      outputSchema: reconciledResultSchema,
      annotations: write(true),
    },
    async ({ ids, reconciled }) =>
      change((store) => {
        const updated = store.setReconciled(ids, reconciled);
        return reply(`${updated.length} transactions marked ${reconciled ? "reconciled" : "unreconciled"}.`, {
          updated: updated.length,
          ids: updated.map((t) => t.id),
          reconciled,
        });
      }),
  );

  server.registerTool(
    "categorize_transactions",
    {
      title: "Categorize transactions",
      description:
        "Give one or more transactions a category, and optionally a counterparty, in one step. Transfers take no " +
        "category. Pass category null to send them back to review.",
      inputSchema: z.object({
        ids: z.array(z.string()).min(1).describe("Transaction ids"),
        category: z.string().nullable().describe("Category id or name; null to uncategorize"),
        counterparty: z.string().nullable().optional().describe("Also set this counterparty; null clears it"),
      }),
      outputSchema: categorizeResultSchema,
      annotations: write(true),
    },
    async ({ ids, category, counterparty }) =>
      change((store) => {
        const data = store.data;
        const result = store.categorize(ids, category, counterparty);
        const remaining = uncategorized(data).length;
        const what = result.category ? `as ${result.category.name}` : "back to review";
        const who = result.counterparty ? `, counterparty ${result.counterparty.name}` : "";
        const kind = result.category?.kind;
        const refunds = kind ? result.transactions.filter((t) => t.direction !== "transfer" && (t.direction === "in") !== (kind === "income")).length : 0;
        const note = refunds
          ? ` ${refunds} of them run against the category (money ${kind === "income" ? "out on an income" : "in on an expense"} ` +
            "category) and are booked as refunds that reduce it; check that is intended."
          : "";
        return reply(`${result.transactions.length} transactions categorized ${what}${who}. ${remaining} left to review.${note}`, {
          updated: result.transactions.length,
          category: result.category && { id: result.category.id, name: result.category.name },
          counterparty: result.counterparty && { id: result.counterparty.id, name: result.counterparty.name },
          transactions: result.transactions.map((t) => transactionRow(data, t)),
          remainingUncategorized: remaining,
        });
      }),
  );

  server.registerTool(
    "import_bank_statement",
    {
      title: "Import bank statement",
      description:
        "Import a bank statement CSV into one account. Map the CSV's columns; each row becomes an uncategorized " +
        "transaction (positive = money in). Rows the account already has (same date, amount and memo) are " +
        "skipped, so re-importing an overlapping statement is safe. Use dry_run to preview.",
      inputSchema: z.object({
        account: z.string().describe(`Account id or name: ${accountNames}`),
        csv: z.string().describe("The CSV text, header row first unless has_header is false"),
        mapping: z.object({
          date: column,
          amount: column.optional().describe("One signed amount column; or use money_in / money_out"),
          money_in: column.optional().describe("Unsigned credit column"),
          money_out: column.optional().describe("Unsigned debit column"),
          description: z.union([column, z.array(column)]).describe("Memo column(s), joined when several"),
          counterparty: column.optional().describe("Payer/payee column, matched to counterparties by exact name"),
          date_format: z.enum(DATE_FORMATS).optional().describe("Default YYYY-MM-DD"),
          delimiter: z.enum([",", ";", "\t"]).optional().describe("Detected from the header when omitted"),
          has_header: z.boolean().optional().describe("Default true"),
          invert_sign: z.boolean().optional().describe("For exports where a positive amount is a charge"),
        }),
        rate: z.number().positive().optional().describe("Base currency per 1 unit, for an account in another currency"),
        dry_run: z.boolean().optional().describe("Report what would be created without saving"),
      }),
      outputSchema: importResultSchema,
      annotations: write(true),
    },
    async ({ account, csv, mapping, rate, dry_run }) =>
      change((store) => {
        const data = store.data;
        const outcome = store.importStatement(
          account,
          csv,
          {
            date: mapping.date,
            amount: mapping.amount,
            moneyIn: mapping.money_in,
            moneyOut: mapping.money_out,
            description: mapping.description,
            counterparty: mapping.counterparty,
            dateFormat: mapping.date_format,
            delimiter: mapping.delimiter,
            hasHeader: mapping.has_header,
            invertSign: mapping.invert_sign,
          },
          { rate, dryRun: dry_run },
        );
        const result = {
          account: { id: outcome.account.id, name: outcome.account.name },
          dryRun: dry_run ?? false,
          created: outcome.created.length,
          skipped: outcome.duplicates.length,
          failed: outcome.errors.length,
          duplicates: outcome.duplicates.map((d) => ({ line: d.line, date: d.date, amount: d.amount, description: d.description })),
          errors: outcome.errors,
          transactions: outcome.created.map((t) => transactionRow(data, t)),
        };
        const lines = [
          `${dry_run ? "Dry run: would create" : "Created"} ${result.created} transactions in ${outcome.account.name}; ` +
            `skipped ${result.skipped} already in the books; ${result.failed} rows failed.`,
          ...outcome.errors.map((e) => `  line ${e.line}: ${e.message}`),
          ...(result.created > 0 && !dry_run ? ["They are uncategorized: categorize_transactions next."] : []),
        ];
        return reply(lines.join("\n"), result);
      }),
  );

  // -------------------------------------------------------------------------
  // Invoices
  // -------------------------------------------------------------------------

  registerAppTool(
    server,
    "create_invoice",
    {
      title: "Create invoice",
      description:
        "Create an invoice with the next number (INV-0001, …). It starts as a draft unless send is true. " +
        "Prices are net of VAT; VAT is added per line.",
      inputSchema: z.object({
        client: z.string().describe("Client id or name (create_counterparty first if new)"),
        lines: z.array(lineInput).min(1),
        issue_date: day.optional().describe("Default today"),
        due_date: day.optional().describe("Default issue date + due_days"),
        due_days: z.number().int().min(0).optional().describe("Payment terms in days, default 14"),
        currency: z.string().length(3).optional().describe("ISO code, default the base currency"),
        notes: z.string().optional(),
        category: z.string().optional().describe('Income category for its payments, default "Services"'),
        send: z.boolean().optional().describe("Mark as sent right away"),
      }),
      outputSchema: invoiceViewSchema,
      annotations: write(false),
      _meta: { ui: { resourceUri: INVOICE_URI } },
    },
    async (input) =>
      change((store) => {
        const data = store.data;
        const invoice = store.createInvoice({
          client: input.client,
          lines: toLines(input.lines),
          issueDate: input.issue_date,
          dueDate: input.due_date,
          dueDays: input.due_days,
          currency: input.currency,
          notes: input.notes,
          category: input.category,
          send: input.send,
        });
        const view = buildInvoiceView(data, invoice);
        return reply(`Created ${summarizeInvoice(view, data)}`, view);
      }),
  );

  registerAppTool(
    server,
    "update_invoice",
    {
      title: "Update invoice",
      description:
        'action "send" marks a draft as sent; "void" cancels an invoice with no payments; "edit" changes a draft ' +
        "(only the fields given; lines replace all lines).",
      inputSchema: z.object({
        number: z.string().describe('e.g. "INV-0012"'),
        action: z.enum(["send", "void", "edit"]),
        client: z.string().optional(),
        lines: z.array(lineInput).min(1).optional(),
        issue_date: day.optional(),
        due_date: day.optional(),
        due_days: z.number().int().min(0).optional(),
        currency: z.string().length(3).optional(),
        notes: z.string().nullable().optional(),
        category: z.string().optional(),
      }),
      outputSchema: invoiceViewSchema,
      annotations: write(false),
      _meta: { ui: { resourceUri: INVOICE_URI } },
    },
    async (input) =>
      change((store) => {
        const data = store.data;
        const invoice = store.updateInvoice(input.number, input.action, {
          client: input.client,
          lines: input.lines && toLines(input.lines),
          issueDate: input.issue_date,
          dueDate: input.due_date,
          dueDays: input.due_days,
          currency: input.currency,
          notes: input.notes,
          category: input.category,
        });
        const view = buildInvoiceView(data, invoice);
        const verb = input.action === "send" ? "Sent" : input.action === "void" ? "Voided" : "Updated";
        return reply(`${verb} ${summarizeInvoice(view, data)}`, view);
      }),
  );

  server.registerTool(
    "record_payment",
    {
      title: "Record payment",
      description:
        "Record money received against a sent invoice. Either link an incoming transaction already in the books " +
        "(transaction_id, e.g. from a statement import) or create one (amount defaults to the balance due, " +
        "account to the first bank account in the invoice currency). Partial payments are fine; more than the " +
        "balance due is refused.",
      inputSchema: z.object({
        number: z.string().describe('Invoice number, e.g. "INV-0012"'),
        transaction_id: z.string().optional().describe("Link this existing incoming transaction instead of creating one"),
        amount: amount.optional().describe("Major units in the invoice currency; default the balance due"),
        base_amount: amount.optional().describe("Base-currency value when the invoice is in another currency"),
        date: day.optional().describe("Default today"),
        account: z.string().optional().describe("Receiving account id or name"),
      }),
      outputSchema: paymentResultSchema,
      annotations: write(false),
    },
    async (input) =>
      change((store) => {
        const data = store.data;
        const { invoice, payment } = store.recordPayment(input.number, {
          transactionId: input.transaction_id,
          amount: input.amount,
          baseAmount: input.base_amount,
          date: input.date,
          account: input.account,
        });
        const summary = invoiceSummary(data, invoice, store.today);
        const row = transactionRow(data, payment);
        return reply(
          `Payment ${row.id} of ${m(payment.amount, invoice.currency)} recorded on ${invoice.number}. ` +
            `Now ${describeInvoice(summary, data)}`,
          { invoice: summary, payment: row },
        );
      }),
  );

  // -------------------------------------------------------------------------
  // Chart of categories and counterparties
  // -------------------------------------------------------------------------

  server.registerTool(
    "create_counterparty",
    {
      title: "Create counterparty",
      description: "Add a client or vendor.",
      inputSchema: z.object({
        name: z.string().min(1),
        kind: z.enum(COUNTERPARTY_KINDS),
        tax_id: z.string().optional().describe("INN or other tax id"),
        email: z.string().optional(),
      }),
      outputSchema: counterpartySchema,
      annotations: write(false),
    },
    async ({ name, kind, tax_id, email }) =>
      change((store) => {
        const counterparty = store.createCounterparty({ name, kind, taxId: tax_id, email });
        return reply(`Created ${counterparty.kind} ${counterparty.name} (${counterparty.id}).`, { ...counterparty });
      }),
  );

  server.registerTool(
    "create_category",
    {
      title: "Create category",
      description: "Add an income or expense category to the chart.",
      inputSchema: z.object({ name: z.string().min(1), kind: z.enum(CATEGORY_KINDS) }),
      outputSchema: categorySchema,
      annotations: write(false),
    },
    async ({ name, kind }) =>
      change((store) => {
        const category = store.createCategory({ name, kind });
        return reply(`Created ${category.kind} category ${category.name} (${category.id}).`, { ...category });
      }),
  );

  server.registerTool(
    "update_category",
    {
      title: "Update category",
      description: "Rename a category, or archive it so it is no longer offered (its history stays).",
      inputSchema: z.object({
        category: z.string().describe("Category id or name"),
        name: z.string().optional(),
        archived: z.boolean().optional(),
      }),
      outputSchema: categorySchema,
      annotations: write(true),
    },
    async ({ category: query, name, archived }) =>
      change((store) => {
        const category = store.updateCategory(query, { name, archived });
        return reply(`Category ${category.name} (${category.id})${category.archived ? ", archived" : ""}.`, { ...category });
      }),
  );

  for (const view of VIEWS) {
    registerAppResource(
      server,
      view.name,
      view.uri,
      { mimeType: RESOURCE_MIME_TYPE, description: view.description },
      async (): Promise<ReadResourceResult> => ({
        contents: [
          {
            uri: view.uri,
            mimeType: RESOURCE_MIME_TYPE,
            text: await fs.readFile(path.join(appDir, view.file), "utf-8"),
          },
        ],
      }),
    );
  }

  return server;
}
