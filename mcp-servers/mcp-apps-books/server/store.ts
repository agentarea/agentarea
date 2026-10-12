import type { Database } from "bun:sqlite";
import { readRows, syncRows, type Rows } from "@kit/store/rows.ts";
import type {
  Account,
  BooksData,
  Category,
  CategoryKind,
  Counterparty,
  CounterpartyKind,
  Direction,
  Invoice,
  InvoiceLine,
  Transaction,
} from "../shared/books.ts";
import { formatMoney, minorDigits, roundMinor, toMinor } from "../shared/money.ts";
import { addDays, isDate } from "../shared/period.ts";
import { invoicePayments, invoiceSummary, invoiceTotals, todayOf } from "./ledger.ts";
import { fromRows, TABLES, toRows } from "./db.ts";
import { parseStatement, planImport, type StatementMapping } from "./statement.ts";

/** A major-unit amount as the caller typed it: 1250.5, "1250.50", "1 250,50". */
export type Amount = number | string;

export interface TransactionInput {
  date?: string;
  account: string;
  direction: Direction;
  amount: Amount;
  baseAmount?: Amount;
  toAccount?: string;
  toAmount?: Amount;
  counterparty?: string | null;
  category?: string | null;
  description: string;
  attachments?: string[];
  reconciled?: boolean;
}

export type TransactionPatch = Partial<Omit<TransactionInput, "attachments">> & {
  attachments?: string[];
  addAttachments?: string[];
};

export interface InvoiceLineInput {
  description: string;
  quantity: number;
  unitPrice: Amount;
  vatRate?: number | null;
}

export interface InvoiceInput {
  client: string;
  issueDate?: string;
  dueDate?: string;
  dueDays?: number;
  currency?: string;
  lines: InvoiceLineInput[];
  notes?: string | null;
  category?: string | null;
}

export interface PaymentInput {
  amount?: Amount;
  baseAmount?: Amount;
  date?: string;
  account?: string;
  transactionId?: string;
}

/** A transaction about to be composed: ids resolved, amounts in minor units. */
interface Draft {
  date: string;
  accountId: string;
  direction: Direction;
  amount: number;
  baseAmount?: number;
  toAccountId: string | null;
  toAmount?: number;
  counterpartyId: string | null;
  categoryId: string | null;
  description: string;
  attachments: string[];
  reconciled: boolean;
}

const nowIso = () => new Date().toISOString();

function nextId(prefix: string, items: { id: string }[], width: number): string {
  const max = items.reduce((m, item) => {
    const n = Number(item.id.slice(prefix.length));
    return item.id.startsWith(prefix) && Number.isInteger(n) ? Math.max(m, n) : m;
  }, 0);
  return `${prefix}${String(max + 1).padStart(width, "0")}`;
}

/**
 * Finds one record by id, exact name, or a name fragment that matches only
 * one record; anything else is an error that lists what exists.
 */
function resolve<T extends { id: string; name: string }>(items: T[], query: string, noun: string, hint = ""): T {
  const q = query.trim().toLowerCase();
  const byId = items.find((item) => item.id.toLowerCase() === q);
  if (byId) return byId;
  const exact = items.filter((item) => item.name.toLowerCase() === q);
  if (exact.length === 1) return exact[0];
  const partial = items.filter((item) => item.name.toLowerCase().includes(q));
  if (partial.length === 1) return partial[0];
  const candidates = (partial.length > 1 ? partial : items).slice(0, 12).map((item) => `${item.name} (${item.id})`);
  throw new Error(
    `${partial.length > 1 ? `"${query}" matches several ${noun}s` : `No ${noun} matches "${query}"`}. ` +
      `${hint}Known: ${candidates.join(", ")}${items.length > 12 && partial.length <= 1 ? ", …" : ""}`,
  );
}

function checkDate(value: string, field: string): string {
  if (!isDate(value)) throw new Error(`${field} must be a date as YYYY-MM-DD, got "${value}"`);
  return value;
}

/**
 * The books as they stand in one store transaction (or read): loaded from the
 * database's rows, changed in memory after every mutation is validated in full,
 * and written back by `save`, which touches only the rows that changed.
 */
export class BooksStore {
  readonly #rows: Rows;

  /** `rows` are what `data` was loaded from; without them, `save` writes every row as new. */
  constructor(
    readonly data: BooksData,
    rows: Rows = {},
  ) {
    this.#rows = rows;
  }

  static load(db: Database): BooksStore {
    const rows = readRows(db, TABLES);
    return new BooksStore(fromRows(rows), rows);
  }

  /** Writes what changed since `load` into `db`, inside the caller's transaction. */
  save(db: Database): void {
    syncRows(db, TABLES, this.#rows, toRows(this.data));
  }

  get today(): string {
    return todayOf(this.data);
  }

  get base(): string {
    return this.data.book.baseCurrency;
  }

  money(minor: number, currency = this.base): string {
    return formatMoney(minor, currency, this.data.book.locale);
  }

  // -------------------------------------------------------------------------
  // Lookups
  // -------------------------------------------------------------------------

  account(query: string): Account {
    return resolve(this.data.accounts, query, "account");
  }

  category(query: string): Category {
    return resolve(this.data.categories, query, "category", "Create one with create_category. ");
  }

  counterparty(query: string): Counterparty {
    return resolve(this.data.counterparties, query, "counterparty", "Create one with create_counterparty. ");
  }

  invoice(query: string): Invoice {
    const q = query.trim().toUpperCase();
    const invoice = this.data.invoices.find((i) => i.number.toUpperCase() === q || i.id.toUpperCase() === q);
    if (!invoice) {
      const numbers = this.data.invoices.map((i) => i.number);
      throw new Error(`No invoice ${query}. Invoices run ${numbers[0] ?? "—"} to ${numbers.at(-1) ?? "—"}`);
    }
    return invoice;
  }

  transaction(id: string): Transaction {
    const transaction = this.data.transactions.find((t) => t.id === id);
    if (!transaction) throw new Error(`No transaction with id ${id}`);
    return transaction;
  }

  // -------------------------------------------------------------------------
  // Transactions
  // -------------------------------------------------------------------------

  /** Checks one transaction as it would stand in the books, together with every other one. */
  #validate(t: Transaction) {
    checkDate(t.date, "date");
    const account = this.data.accounts.find((a) => a.id === t.accountId)!;
    if (!Number.isSafeInteger(t.amount) || t.amount <= 0) {
      throw new Error("amount must be positive; the direction (in / out / transfer) carries the sign");
    }
    if (t.direction === "transfer") {
      if (!t.transferAccountId) throw new Error("A transfer needs to_account: the book's own account receiving the money");
      if (t.transferAccountId === t.accountId) throw new Error("A transfer must go to a different account");
      if (t.categoryId !== null) {
        throw new Error(
          "A transfer between your own accounts is neither income nor expense and cannot have a category. " +
            "Use direction in or out for money that leaves or enters the business.",
        );
      }
      if (t.invoiceId !== null) throw new Error("A transfer cannot pay an invoice");
      if (!t.transferAmount || t.transferAmount <= 0) throw new Error("to_amount must be positive");
    } else if (t.transferAccountId !== null || t.transferAmount !== null) {
      throw new Error("to_account and to_amount are for transfers only");
    }
    if (!Number.isSafeInteger(t.baseAmount) || t.baseAmount <= 0) {
      throw new Error(`base_amount must be positive (${this.base})`);
    }
    if (account.currency === this.base && t.baseAmount !== t.amount) {
      throw new Error(`${account.name} is in ${this.base}, so base_amount must equal amount`);
    }
    if (t.invoiceId) {
      const invoice = this.data.invoices.find((i) => i.id === t.invoiceId)!;
      if (t.direction === "transfer") throw new Error("A transfer cannot pay an invoice");
      if (account.currency !== invoice.currency) {
        throw new Error(`${invoice.number} is in ${invoice.currency}; ${account.name} is in ${account.currency}`);
      }
      const others = invoicePayments(this.data, invoice.id).filter((p) => p.id !== t.id);
      const paid = others.reduce((sum, p) => sum + (p.direction === "in" ? p.amount : -p.amount), 0);
      const total = invoiceTotals(invoice.lines).total;
      const after = paid + (t.direction === "in" ? t.amount : -t.amount);
      if (after > total) {
        throw new Error(
          `Payment of ${this.money(t.amount, invoice.currency)} exceeds the balance due on ${invoice.number}: ` +
            `${this.money(total - paid, invoice.currency)}`,
        );
      }
    }
  }

  /** Turns a draft with resolved ids and minor amounts into a transaction, filling transfer and base amounts. */
  #compose(draft: Draft, existing?: Transaction): Transaction {
    const accountOf = (id: string) => this.data.accounts.find((a) => a.id === id)!;
    const account = accountOf(draft.accountId);
    let transferAccountId: string | null = null;
    let transferAmount: number | null = null;
    if (draft.direction === "transfer") {
      if (!draft.toAccountId) throw new Error("A transfer needs to_account: the book's own account receiving the money");
      const to = accountOf(draft.toAccountId);
      transferAccountId = to.id;
      if (to.currency === account.currency) {
        transferAmount = draft.toAmount ?? draft.amount;
        if (transferAmount !== draft.amount) throw new Error("Both accounts share a currency, so to_amount must equal amount");
      } else {
        if (draft.toAmount === undefined) {
          throw new Error(`${to.name} is in ${to.currency}: pass to_amount, what it received in ${to.currency}`);
        }
        transferAmount = draft.toAmount;
      }
    }
    let baseAmount = draft.baseAmount;
    if (account.currency === this.base) baseAmount = draft.amount;
    else if (transferAccountId && accountOf(transferAccountId).currency === this.base) baseAmount = transferAmount!;
    if (baseAmount === undefined) {
      throw new Error(`${account.name} is in ${account.currency}: pass base_amount, what this was worth in ${this.base}`);
    }
    return {
      id: existing?.id ?? nextId("tx_", this.data.transactions, 5),
      date: checkDate(draft.date, "date"),
      accountId: account.id,
      direction: draft.direction,
      amount: draft.amount,
      baseAmount,
      transferAccountId,
      transferAmount,
      counterpartyId: draft.counterpartyId,
      categoryId: draft.categoryId,
      description: draft.description.trim(),
      bankMemo: existing?.bankMemo ?? null,
      invoiceId: existing?.invoiceId ?? null,
      reconciled: draft.reconciled,
      attachments: draft.attachments,
      source: existing?.source ?? "manual",
      createdAt: existing?.createdAt ?? nowIso(),
    };
  }

  recordTransaction(input: TransactionInput): Transaction {
    const account = this.account(input.account);
    if (account.archived) throw new Error(`${account.name} is archived`);
    const to = input.toAccount ? this.account(input.toAccount) : null;
    const transaction = this.#compose({
      date: input.date ?? this.today,
      accountId: account.id,
      direction: input.direction,
      amount: toMinor(input.amount, account.currency),
      baseAmount: input.baseAmount === undefined ? undefined : toMinor(input.baseAmount, this.base),
      toAccountId: to?.id ?? null,
      toAmount: input.toAmount === undefined || !to ? undefined : toMinor(input.toAmount, to.currency),
      counterpartyId: input.counterparty ? this.counterparty(input.counterparty).id : null,
      categoryId: input.category ? this.category(input.category).id : null,
      description: input.description,
      attachments: input.attachments ?? [],
      reconciled: input.reconciled ?? false,
    });
    this.#validate(transaction);
    this.data.transactions.push(transaction);
    return transaction;
  }

  updateTransaction(id: string, patch: TransactionPatch): Transaction {
    const current = this.transaction(id);
    const moneyFields = ["date", "account", "direction", "amount", "baseAmount", "toAccount", "toAmount"] as const;
    if (current.reconciled && patch.reconciled !== false && moneyFields.some((key) => patch[key] !== undefined)) {
      throw new Error(
        `${id} is reconciled against the bank; pass reconciled=false with the change to edit its date, account or amount`,
      );
    }
    const account = patch.account ? this.account(patch.account) : this.data.accounts.find((a) => a.id === current.accountId)!;
    const sameAccount = account.id === current.accountId;
    if (!sameAccount && patch.amount === undefined && account.currency !== this.data.accounts.find((a) => a.id === current.accountId)!.currency) {
      throw new Error(`${account.name} is in ${account.currency}: pass amount in that currency`);
    }
    const amount = patch.amount === undefined ? current.amount : toMinor(patch.amount, account.currency);
    const direction = patch.direction ?? current.direction;
    const to = direction !== "transfer" ? null : patch.toAccount ? this.account(patch.toAccount) : current.transferAccountId ? this.data.accounts.find((a) => a.id === current.transferAccountId)! : null;
    // Recorded base and transfer amounts still hold while the amount and accounts stay.
    const unchanged = sameAccount && amount === current.amount;
    const next = this.#compose(
      {
        date: patch.date ?? current.date,
        accountId: account.id,
        direction,
        amount,
        baseAmount: patch.baseAmount !== undefined ? toMinor(patch.baseAmount, this.base) : unchanged ? current.baseAmount : undefined,
        toAccountId: to?.id ?? null,
        toAmount:
          to && patch.toAmount !== undefined
            ? toMinor(patch.toAmount, to.currency)
            : to && unchanged && to.id === current.transferAccountId
              ? (current.transferAmount ?? undefined)
              : undefined,
        counterpartyId:
          patch.counterparty === undefined
            ? current.counterpartyId
            : patch.counterparty
              ? this.counterparty(patch.counterparty).id
              : null,
        categoryId:
          patch.category !== undefined
            ? patch.category
              ? this.category(patch.category).id
              : null
            : direction === "transfer"
              ? null
              : current.categoryId,
        description: patch.description ?? current.description,
        attachments: [...(patch.attachments ?? current.attachments), ...(patch.addAttachments ?? [])],
        reconciled: patch.reconciled ?? current.reconciled,
      },
      current,
    );
    this.#validate(next);
    Object.assign(current, next);
    return current;
  }

  deleteTransaction(id: string): void {
    const transaction = this.transaction(id);
    if (transaction.reconciled) {
      throw new Error(`${id} is reconciled against the bank; unreconcile it first (set_reconciled) to delete it`);
    }
    this.data.transactions.splice(this.data.transactions.indexOf(transaction), 1);
  }

  setReconciled(ids: string[], reconciled: boolean): Transaction[] {
    const transactions = ids.map((id) => this.transaction(id));
    for (const t of transactions) t.reconciled = reconciled;
    return transactions;
  }

  categorize(ids: string[], categoryQuery: string | null, counterpartyQuery?: string | null) {
    if (ids.length === 0) throw new Error("Pass at least one transaction id");
    const transactions = [...new Set(ids)].map((id) => this.transaction(id));
    const transfers = transactions.filter((t) => t.direction === "transfer").map((t) => t.id);
    if (categoryQuery && transfers.length > 0) {
      throw new Error(
        `${transfers.join(", ")} ${transfers.length === 1 ? "is a transfer" : "are transfers"} between your own accounts ` +
          "and cannot have a category",
      );
    }
    const category = categoryQuery ? this.category(categoryQuery) : null;
    if (category?.archived) throw new Error(`Category ${category.name} is archived`);
    const counterparty = counterpartyQuery ? this.counterparty(counterpartyQuery) : null;
    for (const t of transactions) {
      if (t.direction !== "transfer") t.categoryId = category?.id ?? null;
      if (counterparty) t.counterpartyId = counterparty.id;
      else if (counterpartyQuery === null) t.counterpartyId = null;
    }
    return { transactions, category, counterparty };
  }

  importStatement(accountQuery: string, csv: string, mapping: StatementMapping, options: { rate?: Amount; dryRun?: boolean }) {
    const account = this.account(accountQuery);
    if (account.archived) throw new Error(`${account.name} is archived`);
    const { rows, errors } = parseStatement(csv, mapping, account.currency);
    const { fresh, duplicates } = planImport(this.data.transactions, account.id, rows);
    let rate: number | null = null;
    if (account.currency !== this.base) {
      if (options.rate === undefined) {
        throw new Error(`${account.name} is in ${account.currency}: pass rate, ${this.base} per 1 ${account.currency}`);
      }
      rate = Number(options.rate);
      if (!(rate > 0)) throw new Error("rate must be a positive number");
    }
    const byName = new Map(this.data.counterparties.map((c) => [c.name.toLowerCase(), c.id]));
    const created: Transaction[] = [];
    const pool = [...this.data.transactions];
    for (const row of fresh) {
      const amount = Math.abs(row.amount);
      const transaction: Transaction = {
        id: nextId("tx_", pool, 5),
        date: row.date,
        accountId: account.id,
        direction: row.amount > 0 ? "in" : "out",
        amount,
        baseAmount: rate === null ? amount : roundMinor(amount * rate * 10 ** (minorDigits(this.base) - minorDigits(account.currency))),
        transferAccountId: null,
        transferAmount: null,
        counterpartyId: (row.counterpartyName && byName.get(row.counterpartyName.toLowerCase())) || null,
        categoryId: null,
        description: row.description,
        bankMemo: row.description,
        invoiceId: null,
        reconciled: false,
        attachments: [],
        source: "import",
        createdAt: nowIso(),
      };
      pool.push(transaction);
      created.push(transaction);
    }
    if (!options.dryRun) this.data.transactions.push(...created);
    return { account, created, duplicates, errors };
  }

  // -------------------------------------------------------------------------
  // Invoices
  // -------------------------------------------------------------------------

  #lines(lines: InvoiceLineInput[], currency: string): InvoiceLine[] {
    if (lines.length === 0) throw new Error("An invoice needs at least one line");
    return lines.map((line, index) => {
      const at = `Line ${index + 1}`;
      if (!line.description.trim()) throw new Error(`${at}: description is empty`);
      if (!(line.quantity > 0)) throw new Error(`${at}: quantity must be positive`);
      const unitPrice = toMinor(line.unitPrice, currency);
      if (unitPrice < 0) throw new Error(`${at}: unit price cannot be negative`);
      const vatRate = line.vatRate ?? null;
      if (vatRate !== null && !(vatRate >= 0 && vatRate <= 100)) throw new Error(`${at}: VAT rate is a percent, 0–100`);
      return { description: line.description.trim(), quantity: line.quantity, unitPrice, vatRate };
    });
  }

  #incomeCategory(query: string | null | undefined): string | null {
    if (!query) return null;
    const category = this.category(query);
    if (category.kind !== "income") throw new Error(`${category.name} is an expense category; invoices book income`);
    return category.id;
  }

  createInvoice(input: InvoiceInput & { send?: boolean }): Invoice {
    const client = this.counterparty(input.client);
    const currency = (input.currency ?? this.base).toUpperCase();
    formatMoney(0, currency);
    const issueDate = checkDate(input.issueDate ?? this.today, "issue_date");
    const dueDate = checkDate(input.dueDate ?? addDays(issueDate, input.dueDays ?? 14), "due_date");
    if (dueDate < issueDate) throw new Error(`The due date ${dueDate} is before the issue date ${issueDate}`);
    const max = this.data.invoices.reduce((m, i) => Math.max(m, Number(i.number.replace(/\D/g, "")) || 0), 0);
    const invoice: Invoice = {
      id: nextId("inv_", this.data.invoices, 4),
      number: `INV-${String(max + 1).padStart(4, "0")}`,
      counterpartyId: client.id,
      issueDate,
      dueDate,
      currency,
      lines: this.#lines(input.lines, currency),
      notes: input.notes?.trim() || null,
      categoryId: this.#incomeCategory(input.category ?? this.#defaultIncomeCategory()),
      sentAt: null,
      voidedAt: null,
      createdAt: nowIso(),
    };
    if (input.send) {
      if (invoiceTotals(invoice.lines).total <= 0) throw new Error("An invoice with a zero total cannot be sent");
      invoice.sentAt = nowIso();
    }
    this.data.invoices.push(invoice);
    return invoice;
  }

  #defaultIncomeCategory(): string | null {
    const income = this.data.categories.filter((c) => c.kind === "income" && !c.archived);
    return (income.find((c) => c.name.toLowerCase() === "services") ?? income[0])?.id ?? null;
  }

  updateInvoice(query: string, action: "send" | "void" | "edit", edits: Partial<InvoiceInput> = {}): Invoice {
    const invoice = this.invoice(query);
    const status = invoiceSummary(this.data, invoice, this.today).status;
    if (action === "send") {
      if (status !== "draft") throw new Error(`${invoice.number} is ${status}, not a draft; only drafts can be sent`);
      if (invoiceTotals(invoice.lines).total <= 0) throw new Error("An invoice with a zero total cannot be sent");
      invoice.sentAt = nowIso();
      return invoice;
    }
    if (action === "void") {
      if (status === "void") throw new Error(`${invoice.number} is already void`);
      const payments = invoicePayments(this.data, invoice.id);
      if (payments.length > 0) {
        throw new Error(
          `${invoice.number} has payments (${payments.map((p) => p.id).join(", ")}); ` +
            "unlink or delete them before voiding it",
        );
      }
      invoice.voidedAt = nowIso();
      return invoice;
    }
    if (status !== "draft") {
      throw new Error(`${invoice.number} is ${status}; only drafts can be edited. Void it and issue a new one instead`);
    }
    const currency = (edits.currency ?? invoice.currency).toUpperCase();
    formatMoney(0, currency);
    const issueDate = checkDate(edits.issueDate ?? invoice.issueDate, "issue_date");
    const dueDate = checkDate(
      edits.dueDate ?? (edits.dueDays !== undefined ? addDays(issueDate, edits.dueDays) : invoice.dueDate),
      "due_date",
    );
    if (dueDate < issueDate) throw new Error(`The due date ${dueDate} is before the issue date ${issueDate}`);
    const next: Invoice = {
      ...invoice,
      counterpartyId: edits.client ? this.counterparty(edits.client).id : invoice.counterpartyId,
      issueDate,
      dueDate,
      currency,
      lines: edits.lines ? this.#lines(edits.lines, currency) : invoice.lines,
      notes: edits.notes === undefined ? invoice.notes : edits.notes?.trim() || null,
      categoryId: edits.category === undefined ? invoice.categoryId : this.#incomeCategory(edits.category),
    };
    if (currency !== invoice.currency && !edits.lines) {
      throw new Error("Changing the currency needs the lines again, priced in the new currency");
    }
    Object.assign(invoice, next);
    return invoice;
  }

  recordPayment(query: string, input: PaymentInput): { invoice: Invoice; payment: Transaction } {
    const invoice = this.invoice(query);
    const summary = invoiceSummary(this.data, invoice, this.today);
    if (summary.status === "draft") {
      throw new Error(`${invoice.number} is a draft; send it first (update_invoice with action "send")`);
    }
    if (summary.status === "void") throw new Error(`${invoice.number} is void and takes no payments`);
    if (summary.status === "paid") throw new Error(`${invoice.number} is already paid in full`);

    if (input.transactionId) {
      const t = this.transaction(input.transactionId);
      if (t.invoiceId && t.invoiceId !== invoice.id) {
        const other = this.data.invoices.find((i) => i.id === t.invoiceId);
        throw new Error(`${t.id} already pays ${other?.number ?? t.invoiceId}`);
      }
      if (t.direction !== "in") throw new Error(`${t.id} is money ${t.direction === "out" ? "out" : "moved between accounts"}, not a payment received`);
      const next: Transaction = {
        ...t,
        invoiceId: invoice.id,
        counterpartyId: t.counterpartyId ?? invoice.counterpartyId,
        categoryId: t.categoryId ?? invoice.categoryId,
      };
      this.#validate(next);
      Object.assign(t, next);
      return { invoice, payment: t };
    }

    const account = input.account
      ? this.account(input.account)
      : this.data.accounts.find((a) => !a.archived && a.kind === "bank" && a.currency === invoice.currency);
    if (!account) throw new Error(`No bank account in ${invoice.currency}; pass account`);
    const amount = input.amount === undefined ? summary.balanceDue : toMinor(input.amount, invoice.currency);
    if (amount <= 0) throw new Error("The payment amount must be positive");
    if (amount > summary.balanceDue) {
      throw new Error(
        `Payment of ${this.money(amount, invoice.currency)} exceeds the balance due on ${invoice.number}: ` +
          `${this.money(summary.balanceDue, invoice.currency)}`,
      );
    }
    const payment = this.#compose({
      date: input.date ?? this.today,
      accountId: account.id,
      direction: "in",
      amount,
      baseAmount: input.baseAmount === undefined ? undefined : toMinor(input.baseAmount, this.base),
      toAccountId: null,
      counterpartyId: invoice.counterpartyId,
      categoryId: invoice.categoryId,
      description: `Payment for ${invoice.number}`,
      attachments: [],
      reconciled: false,
    });
    payment.invoiceId = invoice.id;
    payment.source = "payment";
    this.#validate(payment);
    this.data.transactions.push(payment);
    return { invoice, payment };
  }

  // -------------------------------------------------------------------------
  // Chart and counterparties
  // -------------------------------------------------------------------------

  createCounterparty(input: { name: string; kind: CounterpartyKind; taxId?: string | null; email?: string | null }) {
    const name = input.name.trim();
    if (!name) throw new Error("name is empty");
    const clash = this.data.counterparties.find((c) => c.name.toLowerCase() === name.toLowerCase());
    if (clash) throw new Error(`${clash.name} already exists (${clash.id})`);
    const counterparty: Counterparty = {
      id: nextId("cp_", this.data.counterparties, 3),
      name,
      kind: input.kind,
      taxId: input.taxId?.trim() || null,
      email: input.email?.trim() || null,
    };
    this.data.counterparties.push(counterparty);
    return counterparty;
  }

  createCategory(input: { name: string; kind: CategoryKind }) {
    const name = input.name.trim();
    if (!name) throw new Error("name is empty");
    const clash = this.data.categories.find((c) => c.name.toLowerCase() === name.toLowerCase());
    if (clash) throw new Error(`${clash.name} already exists (${clash.id}, ${clash.kind})`);
    const category: Category = { id: nextId("cat_", this.data.categories, 3), name, kind: input.kind, archived: false };
    this.data.categories.push(category);
    return category;
  }

  updateCategory(query: string, edits: { name?: string; archived?: boolean }) {
    const category = this.category(query);
    if (edits.name !== undefined) {
      const name = edits.name.trim();
      if (!name) throw new Error("name is empty");
      const clash = this.data.categories.find((c) => c.id !== category.id && c.name.toLowerCase() === name.toLowerCase());
      if (clash) throw new Error(`${clash.name} already exists (${clash.id})`);
      category.name = name;
    }
    if (edits.archived !== undefined) category.archived = edits.archived;
    return category;
  }
}
