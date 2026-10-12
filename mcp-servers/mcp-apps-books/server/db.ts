import type { Database } from "bun:sqlite";
import { insertRows, type Row, type Rows, type Table } from "@kit/store/rows.ts";
import type { Migration } from "@kit/store/store.ts";
import demo from "../data/books.json" with { type: "json" };
import type {
  AccountKind,
  BooksData,
  CategoryKind,
  CounterpartyKind,
  Direction,
  Invoice,
  Transaction,
  TransactionSource,
} from "../shared/books.ts";

export const DB_FILE = "books.sqlite";

/**
 * Migration `i` brings the schema to version `i + 1`. Never edit one that has shipped: append.
 * Money is INTEGER minor units (kopecks, cents) of the currency next to it; dates are YYYY-MM-DD,
 * moments ISO 8601 text.
 */
export const MIGRATIONS: Migration[] = [
  (db) =>
    db.run(`
      CREATE TABLE book (
        id            INTEGER PRIMARY KEY CHECK (id = 1),
        name          TEXT NOT NULL,
        legal_name    TEXT NOT NULL,
        tax_id        TEXT,
        address       TEXT,
        email         TEXT,
        bank_details  TEXT,
        base_currency TEXT NOT NULL CHECK (length(base_currency) = 3),
        locale        TEXT NOT NULL,
        as_of         TEXT
      );
      CREATE TABLE accounts (
        id                   TEXT PRIMARY KEY,
        name                 TEXT NOT NULL,
        kind                 TEXT NOT NULL CHECK (kind IN ('bank', 'cash', 'card')),
        currency             TEXT NOT NULL CHECK (length(currency) = 3),
        number               TEXT,
        opening_date         TEXT NOT NULL,
        opening_balance      INTEGER NOT NULL,
        opening_balance_base INTEGER NOT NULL,
        archived             INTEGER NOT NULL CHECK (archived IN (0, 1))
      );
      CREATE TABLE categories (
        id       TEXT PRIMARY KEY,
        name     TEXT NOT NULL,
        kind     TEXT NOT NULL CHECK (kind IN ('income', 'expense')),
        archived INTEGER NOT NULL CHECK (archived IN (0, 1))
      );
      CREATE UNIQUE INDEX categories_name ON categories (name COLLATE NOCASE);
      CREATE TABLE counterparties (
        id     TEXT PRIMARY KEY,
        name   TEXT NOT NULL,
        kind   TEXT NOT NULL CHECK (kind IN ('client', 'vendor')),
        tax_id TEXT,
        email  TEXT
      );
      CREATE UNIQUE INDEX counterparties_name ON counterparties (name COLLATE NOCASE);
      CREATE TABLE invoices (
        id              TEXT PRIMARY KEY,
        number          TEXT NOT NULL UNIQUE,
        counterparty_id TEXT NOT NULL REFERENCES counterparties (id),
        issue_date      TEXT NOT NULL,
        due_date        TEXT NOT NULL,
        currency        TEXT NOT NULL CHECK (length(currency) = 3),
        notes           TEXT,
        category_id     TEXT REFERENCES categories (id),
        sent_at         TEXT,
        voided_at       TEXT,
        created_at      TEXT NOT NULL,
        CHECK (due_date >= issue_date)
      );
      CREATE INDEX invoices_counterparty ON invoices (counterparty_id);
      CREATE TABLE invoice_lines (
        invoice_id  TEXT NOT NULL REFERENCES invoices (id),
        position    INTEGER NOT NULL,
        description TEXT NOT NULL,
        quantity    REAL NOT NULL CHECK (quantity > 0),
        unit_price  INTEGER NOT NULL CHECK (unit_price >= 0),
        vat_rate    REAL CHECK (vat_rate BETWEEN 0 AND 100),
        PRIMARY KEY (invoice_id, position)
      );
      CREATE TABLE transactions (
        id                  TEXT PRIMARY KEY,
        date                TEXT NOT NULL,
        account_id          TEXT NOT NULL REFERENCES accounts (id),
        direction           TEXT NOT NULL CHECK (direction IN ('in', 'out', 'transfer')),
        amount              INTEGER NOT NULL CHECK (amount > 0),
        base_amount         INTEGER NOT NULL CHECK (base_amount > 0),
        transfer_account_id TEXT REFERENCES accounts (id),
        transfer_amount     INTEGER CHECK (transfer_amount > 0),
        counterparty_id     TEXT REFERENCES counterparties (id),
        category_id         TEXT REFERENCES categories (id),
        description         TEXT NOT NULL,
        bank_memo           TEXT,
        invoice_id          TEXT REFERENCES invoices (id),
        reconciled          INTEGER NOT NULL CHECK (reconciled IN (0, 1)),
        source              TEXT NOT NULL CHECK (source IN ('manual', 'import', 'payment')),
        created_at          TEXT NOT NULL,
        CHECK ((direction = 'transfer') = (transfer_account_id IS NOT NULL)),
        CHECK (direction <> 'transfer' OR (category_id IS NULL AND invoice_id IS NULL))
      );
      CREATE INDEX transactions_account_date ON transactions (account_id, date);
      CREATE INDEX transactions_transfer_account ON transactions (transfer_account_id);
      CREATE INDEX transactions_date ON transactions (date);
      CREATE INDEX transactions_category ON transactions (category_id);
      CREATE INDEX transactions_counterparty ON transactions (counterparty_id);
      CREATE INDEX transactions_invoice ON transactions (invoice_id);
      CREATE TABLE transaction_attachments (
        transaction_id TEXT NOT NULL REFERENCES transactions (id),
        position       INTEGER NOT NULL,
        name           TEXT NOT NULL,
        PRIMARY KEY (transaction_id, position)
      );
    `),
];

export const TABLES: Table[] = [
  {
    name: "book",
    columns: ["id", "name", "legal_name", "tax_id", "address", "email", "bank_details", "base_currency", "locale", "as_of"],
    key: ["id"],
  },
  {
    name: "accounts",
    columns: ["id", "name", "kind", "currency", "number", "opening_date", "opening_balance", "opening_balance_base", "archived"],
    key: ["id"],
  },
  { name: "categories", columns: ["id", "name", "kind", "archived"], key: ["id"] },
  { name: "counterparties", columns: ["id", "name", "kind", "tax_id", "email"], key: ["id"] },
  {
    name: "invoices",
    columns: [
      "id", "number", "counterparty_id", "issue_date", "due_date", "currency", "notes", "category_id", "sent_at",
      "voided_at", "created_at",
    ],
    key: ["id"],
  },
  {
    name: "invoice_lines",
    columns: ["invoice_id", "position", "description", "quantity", "unit_price", "vat_rate"],
    key: ["invoice_id", "position"],
    orderBy: "invoice_id, position",
  },
  {
    name: "transactions",
    columns: [
      "id", "date", "account_id", "direction", "amount", "base_amount", "transfer_account_id", "transfer_amount",
      "counterparty_id", "category_id", "description", "bank_memo", "invoice_id", "reconciled", "source", "created_at",
    ],
    key: ["id"],
  },
  {
    name: "transaction_attachments",
    columns: ["transaction_id", "position", "name"],
    key: ["transaction_id", "position"],
    orderBy: "transaction_id, position",
  },
];

export function toRows(data: BooksData): Rows {
  const b = data.book;
  return {
    book: [
      {
        id: 1, name: b.name, legal_name: b.legalName, tax_id: b.taxId, address: b.address, email: b.email,
        bank_details: b.bankDetails, base_currency: b.baseCurrency, locale: b.locale, as_of: data.asOf ?? null,
      },
    ],
    accounts: data.accounts.map((a) => ({
      id: a.id, name: a.name, kind: a.kind, currency: a.currency, number: a.number, opening_date: a.openingDate,
      opening_balance: a.openingBalance, opening_balance_base: a.openingBalanceBase, archived: a.archived ? 1 : 0,
    })),
    categories: data.categories.map((c) => ({ id: c.id, name: c.name, kind: c.kind, archived: c.archived ? 1 : 0 })),
    counterparties: data.counterparties.map((c) => ({ id: c.id, name: c.name, kind: c.kind, tax_id: c.taxId, email: c.email })),
    invoices: data.invoices.map((i) => ({
      id: i.id, number: i.number, counterparty_id: i.counterpartyId, issue_date: i.issueDate, due_date: i.dueDate,
      currency: i.currency, notes: i.notes, category_id: i.categoryId, sent_at: i.sentAt, voided_at: i.voidedAt,
      created_at: i.createdAt,
    })),
    invoice_lines: data.invoices.flatMap((i) =>
      i.lines.map((l, position) => ({
        invoice_id: i.id, position, description: l.description, quantity: l.quantity, unit_price: l.unitPrice,
        vat_rate: l.vatRate,
      })),
    ),
    transactions: data.transactions.map((t) => ({
      id: t.id, date: t.date, account_id: t.accountId, direction: t.direction, amount: t.amount, base_amount: t.baseAmount,
      transfer_account_id: t.transferAccountId, transfer_amount: t.transferAmount, counterparty_id: t.counterpartyId,
      category_id: t.categoryId, description: t.description, bank_memo: t.bankMemo, invoice_id: t.invoiceId,
      reconciled: t.reconciled ? 1 : 0, source: t.source, created_at: t.createdAt,
    })),
    transaction_attachments: data.transactions.flatMap((t) =>
      t.attachments.map((name, position) => ({ transaction_id: t.id, position, name })),
    ),
  };
}

const str = (v: Row[string]) => v as string;
const opt = (v: Row[string]) => v as string | null;
const int = (v: Row[string]) => v as number;

function groupBy(rows: Row[], column: string): Map<string, Row[]> {
  const groups = new Map<string, Row[]>();
  for (const row of rows) {
    const key = str(row[column]);
    const group = groups.get(key);
    if (group) group.push(row);
    else groups.set(key, [row]);
  }
  return groups;
}

export function fromRows(rows: Rows): BooksData {
  const book = rows.book[0];
  if (!book) {
    throw new Error(
      "The books are empty: their storage holds no book settings or accounts yet, and this app has no tools to add them. " +
        "Demo data is written only when a new instance starts with AGENTAREA_MCP_SEED_DEMO=1.",
    );
  }
  const lines = groupBy(rows.invoice_lines, "invoice_id");
  const attachments = groupBy(rows.transaction_attachments, "transaction_id");
  return {
    version: 1,
    ...(book.as_of === null ? {} : { asOf: str(book.as_of) }),
    book: {
      name: str(book.name), legalName: str(book.legal_name), taxId: opt(book.tax_id), address: opt(book.address),
      email: opt(book.email), bankDetails: opt(book.bank_details), baseCurrency: str(book.base_currency), locale: str(book.locale),
    },
    accounts: rows.accounts.map((a) => ({
      id: str(a.id), name: str(a.name), kind: a.kind as AccountKind, currency: str(a.currency), number: opt(a.number),
      openingDate: str(a.opening_date), openingBalance: int(a.opening_balance), openingBalanceBase: int(a.opening_balance_base),
      archived: a.archived === 1,
    })),
    categories: rows.categories.map((c) => ({
      id: str(c.id), name: str(c.name), kind: c.kind as CategoryKind, archived: c.archived === 1,
    })),
    counterparties: rows.counterparties.map((c) => ({
      id: str(c.id), name: str(c.name), kind: c.kind as CounterpartyKind, taxId: opt(c.tax_id), email: opt(c.email),
    })),
    transactions: rows.transactions.map(
      (t): Transaction => ({
        id: str(t.id),
        date: str(t.date),
        accountId: str(t.account_id),
        direction: t.direction as Direction,
        amount: int(t.amount),
        baseAmount: int(t.base_amount),
        transferAccountId: opt(t.transfer_account_id),
        transferAmount: t.transfer_amount as number | null,
        counterpartyId: opt(t.counterparty_id),
        categoryId: opt(t.category_id),
        description: str(t.description),
        bankMemo: opt(t.bank_memo),
        invoiceId: opt(t.invoice_id),
        reconciled: t.reconciled === 1,
        attachments: (attachments.get(str(t.id)) ?? []).map((a) => str(a.name)),
        source: t.source as TransactionSource,
        createdAt: str(t.created_at),
      }),
    ),
    invoices: rows.invoices.map(
      (i): Invoice => ({
        id: str(i.id),
        number: str(i.number),
        counterpartyId: str(i.counterparty_id),
        issueDate: str(i.issue_date),
        dueDate: str(i.due_date),
        currency: str(i.currency),
        lines: (lines.get(str(i.id)) ?? []).map((l) => ({
          description: str(l.description), quantity: l.quantity as number, unitPrice: int(l.unit_price),
          vatRate: l.vat_rate as number | null,
        })),
        notes: opt(i.notes),
        categoryId: opt(i.category_id),
        sentAt: opt(i.sent_at),
        voidedAt: opt(i.voided_at),
        createdAt: str(i.created_at),
      }),
    ),
  };
}

/** The demo books from `data/books.json` (generated by `bun run seed`). */
export const seedDemo: Migration = (db: Database) => insertRows(db, TABLES, toRows(demo as unknown as BooksData));
