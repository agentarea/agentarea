import { Database } from "bun:sqlite";
import { insertRows, readRows } from "@kit/store/rows.ts";
import { describe, expect, test } from "bun:test";
import demo from "../data/books.json" with { type: "json" };
import type { BooksData, Transaction } from "../shared/books.ts";
import { toMinor } from "../shared/money.ts";
import { isDate, resolvePeriod, shiftPeriod } from "../shared/period.ts";
import {
  accountBalances,
  agingBucket,
  deriveInvoiceStatus,
  invoiceSummary,
  invoiceTotals,
  profitAndLoss,
  receivablesAging,
} from "./ledger.ts";
import { fromRows, MIGRATIONS, seedDemo, TABLES, toRows } from "./db.ts";
import { parseStatement, planImport } from "./statement.ts";
import { BooksStore } from "./store.ts";

let seq = 0;
function tx(fields: Partial<Transaction> & Pick<Transaction, "date" | "direction" | "amount">): Transaction {
  return {
    id: `tx_${String(++seq).padStart(5, "0")}`,
    accountId: "acc_rub",
    baseAmount: fields.amount,
    transferAccountId: null,
    transferAmount: null,
    counterpartyId: null,
    categoryId: null,
    description: "",
    bankMemo: null,
    invoiceId: null,
    reconciled: false,
    attachments: [],
    source: "manual",
    createdAt: "2026-01-01T00:00:00.000Z",
    ...fields,
  };
}

function books(transactions: Transaction[] = [], invoices: BooksData["invoices"] = []): BooksData {
  return {
    version: 1,
    asOf: "2026-03-31",
    book: {
      name: "Test",
      legalName: "Test LLC",
      taxId: null,
      address: null,
      email: null,
      bankDetails: null,
      baseCurrency: "RUB",
      locale: "ru-RU",
    },
    accounts: [
      { id: "acc_rub", name: "Bank", kind: "bank", currency: "RUB", number: null, openingDate: "2025-12-31", openingBalance: 100_000_00, openingBalanceBase: 100_000_00, archived: false },
      { id: "acc_usd", name: "Card", kind: "card", currency: "USD", number: null, openingDate: "2025-12-31", openingBalance: 0, openingBalanceBase: 0, archived: false },
    ],
    categories: [
      { id: "cat_sales", name: "Services", kind: "income", archived: false },
      { id: "cat_soft", name: "Software", kind: "expense", archived: false },
      { id: "cat_rent", name: "Office", kind: "expense", archived: false },
    ],
    counterparties: [
      { id: "cp_client", name: "Client LLC", kind: "client", taxId: null, email: null },
      { id: "cp_vendor", name: "Vendor", kind: "vendor", taxId: null, email: null },
    ],
    transactions,
    invoices,
  };
}

const invoice = (fields: Partial<BooksData["invoices"][number]> = {}): BooksData["invoices"][number] => ({
  id: "inv_0001",
  number: "INV-0001",
  counterpartyId: "cp_client",
  issueDate: "2026-02-01",
  dueDate: "2026-02-15",
  currency: "RUB",
  lines: [{ description: "Work", quantity: 10, unitPrice: 1_000_00, vatRate: 22 }],
  notes: null,
  categoryId: "cat_sales",
  sentAt: "2026-02-01T10:00:00.000Z",
  voidedAt: null,
  createdAt: "2026-02-01T10:00:00.000Z",
  ...fields,
});

describe("money", () => {
  test("parses major units into exact minor units", () => {
    expect(toMinor("1 250,50", "RUB")).toBe(125_050);
    expect(toMinor(1250.5, "RUB")).toBe(125_050);
    expect(toMinor("1,250.50", "USD")).toBe(125_050);
    expect(toMinor("1.250,50", "EUR")).toBe(125_050);
    expect(toMinor("-12", "RUB")).toBe(-1_200);
    expect(toMinor(19.99, "USD")).toBe(1_999);
  });

  test("refuses more decimals than the currency has", () => {
    expect(() => toMinor("12.345", "RUB")).toThrow(/decimal places/);
    expect(() => toMinor(0.1 + 0.2, "RUB")).toThrow();
    expect(() => toMinor("12 рублей", "RUB")).toThrow(/not an amount/);
  });
});

describe("periods", () => {
  test("resolve and shift calendar periods", () => {
    expect(resolvePeriod("month", "2026-02-14")).toMatchObject({ from: "2026-02-01", to: "2026-02-28", label: "Feb 2026" });
    expect(resolvePeriod("quarter", "2026-08-01")).toMatchObject({ from: "2026-07-01", to: "2026-09-30", label: "Q3 2026" });
    expect(shiftPeriod(resolvePeriod("month", "2026-03-31"), -1)).toMatchObject({ from: "2026-02-01", to: "2026-02-28" });
    expect(shiftPeriod(resolvePeriod("year", "2026-05-05"), -1).label).toBe("2025");
  });

  test("only real calendar days are dates", () => {
    expect(isDate("2024-02-29")).toBe(true);
    expect(isDate("2026-02-30")).toBe(false);
    expect(isDate("2026-13-01")).toBe(false);
    expect(isDate("26-01-01")).toBe(false);
  });
});

describe("balances", () => {
  test("opening plus money in, minus money out; a transfer moves between accounts", () => {
    const data = books([
      tx({ date: "2026-01-05", direction: "in", amount: 50_000_00, categoryId: "cat_sales" }),
      tx({ date: "2026-01-06", direction: "out", amount: 12_000_00, categoryId: "cat_rent" }),
      tx({
        date: "2026-01-07",
        direction: "transfer",
        amount: 9_000_00,
        baseAmount: 9_000_00,
        transferAccountId: "acc_usd",
        transferAmount: 100_00,
      }),
      tx({ date: "2026-01-08", accountId: "acc_usd", direction: "out", amount: 40_00, baseAmount: 3_640_00, categoryId: "cat_soft" }),
    ]);
    const balances = accountBalances(data);
    expect(balances.get("acc_rub")).toEqual({ balance: 129_000_00, base: 129_000_00 });
    expect(balances.get("acc_usd")).toEqual({ balance: 60_00, base: 5_360_00 });
    expect(accountBalances(data, "2026-01-05").get("acc_rub")!.balance).toBe(150_000_00);
  });
});

describe("profit and loss", () => {
  test("sums by category, nets refunds, keeps uncategorized lines, ignores transfers", () => {
    const data = books([
      tx({ date: "2026-01-05", direction: "in", amount: 50_000_00, categoryId: "cat_sales" }),
      tx({ date: "2026-01-10", direction: "out", amount: 3_000_00, categoryId: "cat_soft", counterpartyId: "cp_vendor" }),
      tx({ date: "2026-01-12", direction: "in", amount: 500_00, categoryId: "cat_soft", counterpartyId: "cp_vendor" }),
      tx({ date: "2026-01-15", direction: "out", amount: 1_000_00 }),
      tx({ date: "2026-01-16", direction: "in", amount: 700_00 }),
      tx({ date: "2026-01-20", direction: "transfer", amount: 9_000_00, transferAccountId: "acc_usd", transferAmount: 100_00 }),
      tx({ date: "2026-02-01", direction: "out", amount: 99_00, categoryId: "cat_rent" }),
    ]);
    const pnl = profitAndLoss(data, "2026-01-01", "2026-01-31");
    expect(pnl.income).toEqual([
      { categoryId: "cat_sales", name: "Services", amount: 50_000_00, count: 1 },
      { categoryId: null, name: "Uncategorized", amount: 700_00, count: 1 },
    ]);
    expect(pnl.expenses).toEqual([
      { categoryId: "cat_soft", name: "Software", amount: 2_500_00, count: 2 },
      { categoryId: null, name: "Uncategorized", amount: 1_000_00, count: 1 },
    ]);
    expect(pnl.totalIncome).toBe(50_700_00);
    expect(pnl.totalExpenses).toBe(3_500_00);
    expect(pnl.net).toBe(47_200_00);
    expect(pnl.topVendors[0]).toMatchObject({ counterpartyId: "cp_vendor", amount: 2_500_00 });
  });
});

describe("invoices", () => {
  test("VAT is rounded per line", () => {
    const totals = invoiceTotals([
      { description: "A", quantity: 3, unitPrice: 333_33, vatRate: 22 },
      { description: "B", quantity: 1.5, unitPrice: 101, vatRate: 22 },
      { description: "C", quantity: 1, unitPrice: 50_000_00, vatRate: null },
    ]);
    expect(totals.lines.map((l) => [l.net, l.vat])).toEqual([
      [999_99, 220_00],
      [152, 33],
      [50_000_00, 0],
    ]);
    expect(totals.subtotal).toBe(999_99 + 152 + 50_000_00);
    expect(totals.vatTotal).toBe(220_33);
    expect(totals.total).toBe(totals.subtotal + totals.vatTotal);
    expect(totals.vatBreakdown).toEqual([
      { rate: 22, net: 1_001_51, vat: 220_33 },
      { rate: null, net: 50_000_00, vat: 0 },
    ]);
  });

  test("status follows sending, payments, the due date and voiding", () => {
    const base = { sent: true, voided: false, total: 1000, paid: 0, dueDate: "2026-02-15", today: "2026-02-10" };
    expect(deriveInvoiceStatus({ ...base, sent: false })).toBe("draft");
    expect(deriveInvoiceStatus(base)).toBe("sent");
    expect(deriveInvoiceStatus({ ...base, paid: 400 })).toBe("partially_paid");
    expect(deriveInvoiceStatus({ ...base, paid: 1000 })).toBe("paid");
    expect(deriveInvoiceStatus({ ...base, today: "2026-02-16" })).toBe("overdue");
    expect(deriveInvoiceStatus({ ...base, today: "2026-02-16", paid: 400 })).toBe("overdue");
    expect(deriveInvoiceStatus({ ...base, today: "2026-02-15" })).toBe("sent");
    expect(deriveInvoiceStatus({ ...base, voided: true, paid: 1000 })).toBe("void");
  });

  test("payments come from linked incoming transactions; aging buckets by days past due", () => {
    const data = books(
      [tx({ date: "2026-02-20", direction: "in", amount: 4_000_00, invoiceId: "inv_0001", categoryId: "cat_sales" })],
      [
        invoice(),
        invoice({ id: "inv_0002", number: "INV-0002", dueDate: "2026-03-20" }),
        invoice({ id: "inv_0003", number: "INV-0003", dueDate: "2026-04-15" }),
        invoice({ id: "inv_0004", number: "INV-0004", sentAt: null }),
      ],
    );
    const first = invoiceSummary(data, data.invoices[0], "2026-03-31");
    expect(first).toMatchObject({ total: 12_200_00, amountPaid: 4_000_00, balanceDue: 8_200_00, status: "overdue", daysOverdue: 44 });
    expect([0, 1, 30, 31, 60, 61].map(agingBucket)).toEqual(["current", "d1_30", "d1_30", "d31_60", "d31_60", "d60_plus"]);
    const aging = receivablesAging(data, "2026-03-31");
    expect(aging.invoices.map((i) => [i.number, i.bucket])).toEqual([
      ["INV-0001", "d31_60"],
      ["INV-0002", "d1_30"],
      ["INV-0003", "current"],
    ]);
    expect(aging.totals).toEqual([
      { currency: "RUB", current: 12_200_00, d1_30: 12_200_00, d31_60: 8_200_00, d60_plus: 0, total: 32_600_00 },
    ]);
  });
});

describe("bank statement import", () => {
  const csv = [
    "Дата;Сумма;Назначение;Контрагент",
    "05.01.2026;-1 500,00;Coffee;Vendor",
    "05.01.2026;-1 500,00;Coffee;Vendor",
    '06.01.2026;25000;"Payment; invoice 7";Client LLC',
    "30.02.2026;10;Broken;",
  ].join("\n");

  test("parses with a mapping and reports bad rows", () => {
    const { rows, errors } = parseStatement(
      csv,
      { date: "Дата", amount: "Сумма", description: "Назначение", counterparty: "Контрагент", dateFormat: "DD.MM.YYYY" },
      "RUB",
    );
    expect(rows.map((r) => [r.line, r.date, r.amount, r.description])).toEqual([
      [2, "2026-01-05", -1_500_00, "Coffee"],
      [3, "2026-01-05", -1_500_00, "Coffee"],
      [4, "2026-01-06", 25_000_00, "Payment; invoice 7"],
    ]);
    expect(errors).toEqual([{ line: 5, message: '"30.02.2026" is not a DD.MM.YYYY date' }]);
  });

  test("money in / money out columns", () => {
    const { rows } = parseStatement(
      "date,in,out,memo\n2026-01-02,,99.90,Fee\n2026-01-03,100,,Refund",
      { date: "date", moneyIn: "in", moneyOut: "out", description: "memo" },
      "USD",
    );
    expect(rows.map((r) => r.amount)).toEqual([-99_90, 100_00]);
  });

  test("dedupes by date + amount + memo, counting repeats", () => {
    const existing = [
      tx({ date: "2026-01-05", direction: "out", amount: 1_500_00, description: "renamed later", bankMemo: "coffee " }),
    ];
    const { rows } = parseStatement(
      csv,
      { date: 0, amount: 1, description: 2, dateFormat: "DD.MM.YYYY" },
      "RUB",
    );
    const first = planImport(existing, "acc_rub", rows);
    expect(first.duplicates.map((r) => r.line)).toEqual([2]);
    expect(first.fresh.map((r) => r.line)).toEqual([3, 4]);
    expect(planImport(existing, "acc_usd", rows).duplicates).toEqual([]);
  });
});

/** A fresh database at the current schema, foreign keys on, as the app store opens it. */
function database(): Database {
  const db = new Database(":memory:", { strict: true });
  db.run("PRAGMA foreign_keys = ON");
  for (const migrate of MIGRATIONS) migrate(db);
  return db;
}

function stored(data: BooksData): { db: Database; store: BooksStore } {
  const db = database();
  insertRows(db, TABLES, toRows(data));
  return { db, store: BooksStore.load(db) };
}

describe("store rules", () => {
  const open = (data: BooksData) => stored(data).store;

  test("a transfer cannot take a category", async () => {
    const store = await open(books());
    expect(() =>
      store.recordTransaction({ account: "Bank", direction: "transfer", toAccount: "Card", amount: 100, toAmount: 1, category: "Software", description: "x" }),
    ).toThrow(/cannot have a category/);
    const transfer = store.recordTransaction({ account: "Bank", direction: "transfer", toAccount: "Card", amount: 9000, toAmount: 100, description: "top up" });
    expect(transfer).toMatchObject({ amount: 9_000_00, baseAmount: 9_000_00, transferAmount: 100_00 });
    expect(() => store.categorize([transfer.id], "Software")).toThrow(/transfer/);
  });

  test("a foreign-currency account needs its base amount", async () => {
    const store = await open(books());
    expect(() => store.recordTransaction({ account: "acc_usd", direction: "out", amount: 20, description: "x" })).toThrow(/base_amount/);
    expect(store.recordTransaction({ account: "acc_usd", direction: "out", amount: 20, baseAmount: "1 820", description: "x" }).baseAmount).toBe(1_820_00);
  });

  test("payments: partial, then refused above the balance due, never on a draft", async () => {
    const store = await open(books([], [invoice(), invoice({ id: "inv_0002", number: "INV-0002", sentAt: null })]));
    const { payment } = store.recordPayment("inv-0001", { amount: 5000 });
    expect(payment).toMatchObject({ direction: "in", amount: 5_000_00, invoiceId: "inv_0001", categoryId: "cat_sales", counterpartyId: "cp_client" });
    expect(invoiceSummary(store.data, store.data.invoices[0], store.today)).toMatchObject({ amountPaid: 5_000_00, balanceDue: 7_200_00 });
    expect(() => store.recordPayment("INV-0001", { amount: 7_200.01 })).toThrow(/exceeds the balance due/);
    expect(() => store.recordPayment("INV-0002", {})).toThrow(/draft/);
    expect(() => store.updateInvoice("INV-0001", "void")).toThrow(/has payments/);
    store.recordPayment("INV-0001", {});
    expect(invoiceSummary(store.data, store.data.invoices[0], store.today).status).toBe("paid");
  });

  test("statement import is idempotent and saved as rows", () => {
    const { db, store } = stored(books());
    const statement = "date,amount,memo\n2026-03-01,-500,Hosting\n2026-03-02,1000,Client";
    const mapping = { date: "date", amount: "amount", description: "memo" };
    expect(store.importStatement("Bank", statement, mapping, {}).created).toHaveLength(2);
    expect(store.importStatement("Bank", statement, mapping, {}).duplicates).toHaveLength(2);
    store.save(db);
    const saved = BooksStore.load(db).data;
    expect(saved.transactions.map((t) => [t.direction, t.amount, t.categoryId])).toEqual([
      ["out", 500_00, null],
      ["in", 1_000_00, null],
    ]);
  });
});

describe("tables", () => {
  test("the demo books come back from the tables exactly as generated", () => {
    const db = database();
    db.transaction(() => seedDemo(db))();
    expect(fromRows(readRows(db, TABLES))).toEqual(demo as unknown as BooksData);
  });

  test("every kind of change survives save and load", () => {
    const { db, store } = stored(demo as unknown as BooksData);
    const tx = store.recordTransaction({ account: "acc_001", direction: "out", amount: "1 250,50", description: "Coffee", attachments: ["r.pdf"] });
    store.updateTransaction(tx.id, { addAttachments: ["r2.pdf"], description: "Coffee beans" });
    store.categorize([tx.id], store.data.categories.find((c) => c.kind === "expense")!.id);
    const gone = store.recordTransaction({ account: "acc_001", direction: "in", amount: 10, description: "typo" });
    store.deleteTransaction(gone.id);
    const client = store.createCounterparty({ name: "Test Client LLC", kind: "client" });
    store.createCategory({ name: "Test income", kind: "income" });
    store.updateCategory("Test income", { archived: true });
    const invoice = store.createInvoice({ client: client.id, lines: [{ description: "Work", quantity: 1.5, unitPrice: "1000", vatRate: 22 }] });
    store.updateInvoice(invoice.number, "edit", { lines: [{ description: "Work, revised", quantity: 2, unitPrice: 900, vatRate: null }] });
    store.updateInvoice(invoice.number, "send");
    store.recordPayment(invoice.number, { amount: 500 });
    store.setReconciled([tx.id], true);
    store.save(db);
    expect(BooksStore.load(db).data).toEqual(store.data);
  });

  test("a transfer with a category is refused by the schema as well", () => {
    const { db, store } = stored(books());
    const transfer = store.recordTransaction({ account: "Bank", direction: "transfer", toAccount: "Card", amount: 9000, toAmount: 100, description: "top up" });
    store.save(db);
    expect(() => db.run("UPDATE transactions SET category_id = 'cat_sales' WHERE id = ?", [transfer.id])).toThrow(/CHECK constraint/);
  });
});
