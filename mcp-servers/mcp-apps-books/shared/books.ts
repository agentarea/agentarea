export const ACCOUNT_KINDS = ["bank", "cash", "card"] as const;
export type AccountKind = (typeof ACCOUNT_KINDS)[number];

/** A transfer moves money between two of the book's own accounts: it is neither income nor expense. */
export const DIRECTIONS = ["in", "out", "transfer"] as const;
export type Direction = (typeof DIRECTIONS)[number];

export const CATEGORY_KINDS = ["income", "expense"] as const;
export type CategoryKind = (typeof CATEGORY_KINDS)[number];

export const COUNTERPARTY_KINDS = ["client", "vendor"] as const;
export type CounterpartyKind = (typeof COUNTERPARTY_KINDS)[number];

export const INVOICE_STATUSES = ["draft", "sent", "partially_paid", "overdue", "paid", "void"] as const;
export type InvoiceStatus = (typeof INVOICE_STATUSES)[number];

export const TRANSACTION_SOURCES = ["manual", "import", "payment"] as const;
export type TransactionSource = (typeof TRANSACTION_SOURCES)[number];

export const PERIOD_KINDS = ["month", "quarter", "year", "custom"] as const;
export type PeriodKind = (typeof PERIOD_KINDS)[number];

export const AGING_BUCKETS = ["current", "d1_30", "d31_60", "d60_plus"] as const;
export type AgingBucket = (typeof AGING_BUCKETS)[number];

// ---------------------------------------------------------------------------
// The dataset, stored as tables in the app's sqlite database. Every amount is
// an integer in minor units (kopecks, cents) of the currency next to it; every
// date is `YYYY-MM-DD`.
// ---------------------------------------------------------------------------

export interface Book {
  name: string;
  legalName: string;
  taxId: string | null;
  address: string | null;
  email: string | null;
  /** Payment details printed on invoices. */
  bankDetails: string | null;
  baseCurrency: string;
  /** Locale used to format money and dates, e.g. "ru-RU". */
  locale: string;
}

export interface Account {
  id: string;
  name: string;
  kind: AccountKind;
  currency: string;
  /** Masked account or card number, for recognition only. */
  number: string | null;
  openingDate: string;
  openingBalance: number;
  /** The opening balance in the book's base currency. */
  openingBalanceBase: number;
  archived: boolean;
}

export interface Category {
  id: string;
  name: string;
  kind: CategoryKind;
  archived: boolean;
}

export interface Counterparty {
  id: string;
  name: string;
  kind: CounterpartyKind;
  taxId: string | null;
  email: string | null;
}

export interface Transaction {
  id: string;
  date: string;
  accountId: string;
  direction: Direction;
  /** Positive, in the account's currency. */
  amount: number;
  /** The same movement in the book's base currency; reports sum this. */
  baseAmount: number;
  /** Transfers only: the receiving account and what it received in its own currency. */
  transferAccountId: string | null;
  transferAmount: number | null;
  counterpartyId: string | null;
  /** Null means uncategorized: the transaction needs review. Always null for a transfer. */
  categoryId: string | null;
  description: string;
  /** The memo as the bank sent it; kept unchanged so a re-import recognizes the line. */
  bankMemo: string | null;
  invoiceId: string | null;
  reconciled: boolean;
  /** File names or URLs. */
  attachments: string[];
  source: TransactionSource;
  createdAt: string;
}

export interface InvoiceLine {
  description: string;
  quantity: number;
  /** Net of VAT, minor units of the invoice currency. */
  unitPrice: number;
  /** Percent (e.g. 22); null when the line carries no VAT. */
  vatRate: number | null;
}

export interface Invoice {
  id: string;
  number: string;
  counterpartyId: string;
  issueDate: string;
  dueDate: string;
  currency: string;
  lines: InvoiceLine[];
  notes: string | null;
  /** Income category its payments are booked to. */
  categoryId: string | null;
  sentAt: string | null;
  voidedAt: string | null;
  createdAt: string;
}

export interface BooksData {
  version: 1;
  /** A frozen "today" for demo datasets; without it the books follow the real date. */
  asOf?: string;
  book: Book;
  accounts: Account[];
  categories: Category[];
  counterparties: Counterparty[];
  transactions: Transaction[];
  invoices: Invoice[];
}
