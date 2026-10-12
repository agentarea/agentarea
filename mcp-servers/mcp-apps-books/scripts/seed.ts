/**
 * Generates `data/books.json`: twelve months of books for a small software
 * company paid in roubles, with a USD card for foreign SaaS.
 *
 * Every random choice comes from one PRNG with a fixed seed and every date is
 * relative to a fixed `AS_OF`, so running the script twice yields the same file.
 */
import fs from "node:fs/promises";
import path from "node:path";
import type {
  Account,
  BooksData,
  Category,
  Counterparty,
  Invoice,
  InvoiceLine,
  Transaction,
} from "../shared/books.ts";
import { roundMinor } from "../shared/money.ts";
import { addDays, addMonths, msOf } from "../shared/period.ts";
import { invoiceTotals } from "../server/ledger.ts";

const SEED = 0xb00c_2026;
const AS_OF = "2026-09-28";
const START = "2025-10-01";
const MONTHS = 12;
const REVIEW_COUNT = 20;
const OUT = path.join(import.meta.dirname, "..", "data", "books.json");

// mulberry32
let state = SEED >>> 0;
function random(): number {
  state = (state + 0x6d2b79f5) >>> 0;
  let t = state;
  t = Math.imul(t ^ (t >>> 15), t | 1);
  t ^= t + Math.imul(t ^ (t >>> 7), t | 61);
  return ((t ^ (t >>> 14)) >>> 0) / 4_294_967_296;
}
const int = (min: number, max: number) => min + Math.floor(random() * (max - min + 1));
const chance = (p: number) => random() < p;
/** Roubles to kopecks, rounded to whole roubles: bank amounts in this book are round. */
const rub = (roubles: number) => Math.round(roubles) * 100;
const usd = (dollars: number) => Math.round(dollars * 100);

/** The next business day on or after `date`. */
function workday(date: string): string {
  const weekday = new Date(msOf(date)).getUTCDay();
  if (weekday === 6) return addDays(date, 2);
  if (weekday === 0) return addDays(date, 1);
  return date;
}
const monthStart = (m: number) => addMonths(START, m);
const dayOf = (m: number, day: number) => workday(`${monthStart(m).slice(0, 8)}${String(day).padStart(2, "0")}`);
const lastWorkday = (m: number) => {
  let date = addDays(monthStart(m + 1), -1);
  while ([0, 6].includes(new Date(msOf(date)).getUTCDay())) date = addDays(date, -1);
  return date;
};
const ruDate = (date: string) => `${date.slice(8, 10)}.${date.slice(5, 7)}.${date.slice(0, 4)}`;
const RU_MONTHS = ["январь", "февраль", "март", "апрель", "май", "июнь", "июль", "август", "сентябрь", "октябрь", "ноябрь", "декабрь"];
const ruMonth = (date: string) => `${RU_MONTHS[Number(date.slice(5, 7)) - 1]} ${date.slice(0, 4)}`;

/** RUB per 1 USD, one rate per month of the history. */
const USD_RATE = [96.5, 99.2, 101.3, 98.7, 95.4, 92.1, 90.6, 88.3, 86.9, 85.2, 83.9, 82.7];
const rateOn = (date: string) => USD_RATE[Math.max(0, Math.min(MONTHS - 1, monthIndex(date)))];
const monthIndex = (date: string) =>
  (Number(date.slice(0, 4)) - Number(START.slice(0, 4))) * 12 + Number(date.slice(5, 7)) - Number(START.slice(5, 7));

// ---------------------------------------------------------------------------
// The chart, accounts and counterparties
// ---------------------------------------------------------------------------

const book: BooksData["book"] = {
  name: "Northbeam Software",
  legalName: "ООО «Нортбим Софтвер»",
  taxId: "7712345678",
  address: "115054, Москва, ул. Примерная, д. 1, офис 12",
  email: "billing@northbeam.example",
  bankDetails: "Р/с 40702810900000012345 · БИК 044525000 · к/с 30101810400000000000",
  baseCurrency: "RUB",
  locale: "ru-RU",
};

const OPENING = addDays(START, -1);
const accounts: Account[] = [
  {
    id: "acc_001",
    name: "Operating account",
    kind: "bank",
    currency: "RUB",
    number: "•• 2345",
    openingDate: OPENING,
    openingBalance: rub(1_850_000),
    openingBalanceBase: rub(1_850_000),
    archived: false,
  },
  {
    id: "acc_002",
    name: "Reserve account",
    kind: "bank",
    currency: "RUB",
    number: "•• 7781",
    openingDate: OPENING,
    openingBalance: rub(3_000_000),
    openingBalanceBase: rub(3_000_000),
    archived: false,
  },
  {
    id: "acc_003",
    name: "Company card",
    kind: "card",
    currency: "USD",
    number: "•• 4417",
    openingDate: OPENING,
    openingBalance: usd(1_200),
    openingBalanceBase: roundMinor(usd(1_200) * USD_RATE[0]),
    archived: false,
  },
];
const [OPERATING, RESERVE, CARD] = accounts.map((a) => a.id);

const CATEGORY_NAMES = {
  income: ["Subscriptions", "Services", "Other income"],
  expense: ["Payroll", "Taxes", "Cloud & hosting", "Software", "Contractors", "Office", "Marketing", "Bank fees", "Other"],
} as const;
const categories: Category[] = [...CATEGORY_NAMES.income, ...CATEGORY_NAMES.expense].map((name, i) => ({
  id: `cat_${String(i + 1).padStart(3, "0")}`,
  name,
  kind: i < CATEGORY_NAMES.income.length ? "income" : "expense",
  archived: false,
}));
const cat = (name: string) => categories.find((c) => c.name === name)!.id;

const counterparties: Counterparty[] = [];
function party(name: string, kind: Counterparty["kind"], taxId: string | null = null, email: string | null = null) {
  const id = `cp_${String(counterparties.length + 1).padStart(3, "0")}`;
  counterparties.push({ id, name, kind, taxId, email });
  return id;
}

const CLIENTS = {
  polyana: party("ООО «Лесная Поляна»", "client", "7701100001", "buh@polyana.example"),
  kvarc: party("ООО «Кварц Трейд»", "client", "7701100002", "finance@kvarc.example"),
  briz: party("ООО «Бриз Медиа»", "client", "7701100003", "accounts@briz.example"),
  sokolov: party("ИП Соколов Андрей Викторович", "client", "770110000004", "sokolov@mail.example"),
  sfera: party("ООО «Сфера Ритейл»", "client", "7701100005", "ap@sfera.example"),
  polaris: party("ООО «Полярис Логистика»", "client", "7701100006", "buh@polaris.example"),
  granit: party("ООО «Гранит Девелопмент»", "client", "7701100007", "invoices@granit.example"),
  yasen: party("ООО «Ясень Агро»", "client", "7701100008", "office@yasen.example"),
  meridian: party("АО «Меридиан Финанс»", "client", "7701100009", "payables@meridian.example"),
  okto: party("ООО «Окто Лабс»", "client", "7701100010", "hello@okto.example"),
  veter: party("ООО «Северный Ветер»", "client", "7701100011", "buh@veter.example"),
  atlas: party("ООО «Атлас Медтех»", "client", "7701100012", "finance@atlas.example"),
};
const VENDORS = {
  payroll: party("Сотрудники (зарплатный реестр)", "vendor"),
  fns: party("ФНС России", "vendor", "7707329152"),
  yandexCloud: party("Yandex Cloud", "vendor"),
  selectel: party("Selectel", "vendor"),
  aws: party("Amazon Web Services", "vendor"),
  github: party("GitHub", "vendor"),
  figma: party("Figma", "vendor"),
  notion: party("Notion", "vendor"),
  jetbrains: party("JetBrains", "vendor"),
  openai: party("OpenAI", "vendor"),
  kontur: party("СКБ Контур", "vendor"),
  petrov: party("ИП Петров Дмитрий Сергеевич", "vendor", "773300000001"),
  kim: party("ИП Ким Елена Алексеевна", "vendor", "773300000002"),
  orlov: party("ИП Орлов Максим Игоревич", "vendor", "773300000003"),
  ladoga: party("БЦ «Ладога»", "vendor", "7703300004"),
  aqua: party("ООО «Аквалайн»", "vendor", "7703300005"),
  kanc: party("ООО «КанцСнаб»", "vendor", "7703300006"),
  direct: party("Яндекс Директ", "vendor"),
  event: party("ООО «Ивент Про»", "vendor", "7703300007"),
  bank: party("Банк (комиссии)", "vendor"),
  courier: party("ООО «Курьер Сервис»", "vendor", "7703300008"),
};

// ---------------------------------------------------------------------------
// Transactions
// ---------------------------------------------------------------------------

const transactions: Transaction[] = [];

function add(
  date: string,
  accountId: string,
  direction: Transaction["direction"],
  amount: number,
  fields: { counterparty?: string; category?: string; description: string; invoiceId?: string; to?: { account: string; amount: number } },
) {
  if (date > AS_OF || date < START) return;
  const account = accounts.find((a) => a.id === accountId)!;
  const baseAmount =
    account.currency === "RUB"
      ? amount
      : fields.to && accounts.find((a) => a.id === fields.to!.account)!.currency === "RUB"
        ? fields.to.amount
        : roundMinor(amount * rateOn(date));
  transactions.push({
    id: "",
    date,
    accountId,
    direction,
    amount,
    baseAmount,
    transferAccountId: fields.to?.account ?? null,
    transferAmount: fields.to?.amount ?? null,
    counterpartyId: fields.counterparty ?? null,
    categoryId: direction === "transfer" ? null : (fields.category ?? null),
    description: fields.description,
    bankMemo: null,
    invoiceId: fields.invoiceId ?? null,
    reconciled: false,
    attachments: [],
    source: fields.invoiceId ? "payment" : "manual",
    createdAt: `${date}T09:00:00.000Z`,
  });
}

/** Monthly plans: fee in roubles, first and last month index of the history. */
const SUBSCRIPTIONS: { client: string; fee: number; from: number; to: number; contract: string }[] = [
  { client: CLIENTS.polyana, fee: 125_000, from: 0, to: 11, contract: "ПД-2024/031" },
  { client: CLIENTS.kvarc, fee: 79_000, from: 0, to: 11, contract: "ПД-2024/044" },
  { client: CLIENTS.briz, fee: 199_000, from: 0, to: 11, contract: "ПД-2025/002" },
  { client: CLIENTS.sokolov, fee: 34_900, from: 0, to: 6, contract: "ПД-2025/009" },
  { client: CLIENTS.sfera, fee: 249_000, from: 0, to: 11, contract: "ПД-2025/013" },
  { client: CLIENTS.polaris, fee: 169_000, from: 2, to: 11, contract: "ПД-2025/027" },
  { client: CLIENTS.granit, fee: 139_000, from: 0, to: 11, contract: "ПД-2025/018" },
  { client: CLIENTS.yasen, fee: 99_000, from: 5, to: 11, contract: "ПД-2026/004" },
  { client: CLIENTS.meridian, fee: 290_000, from: 4, to: 11, contract: "ПД-2026/001" },
  { client: CLIENTS.okto, fee: 99_000, from: 7, to: 11, contract: "ПД-2026/011" },
  { client: CLIENTS.veter, fee: 55_000, from: 1, to: 11, contract: "ПД-2025/033" },
];
/** Prices went up 8% in January for everyone already subscribed. */
const PRICE_RISE_MONTH = 3;

for (let m = 0; m < MONTHS; m++) {
  const start = monthStart(m);
  const forMonth = ruMonth(start);

  for (const plan of SUBSCRIPTIONS) {
    if (m < plan.from || m > plan.to) continue;
    const fee = m >= PRICE_RISE_MONTH && plan.from < PRICE_RISE_MONTH ? Math.round((plan.fee * 1.08) / 100) * 100 : plan.fee;
    add(dayOf(m, int(3, 12)), OPERATING, "in", rub(fee), {
      counterparty: plan.client,
      category: cat("Subscriptions"),
      description: `Оплата по договору ${plan.contract} за ${forMonth}, в т.ч. НДС 22%`,
    });
  }

  const payroll = 640_000 + m * 14_000;
  add(dayOf(m, 5), OPERATING, "out", rub(payroll * 0.6), {
    counterparty: VENDORS.payroll,
    category: cat("Payroll"),
    description: `Заработная плата за ${ruMonth(addMonths(start, -1))} по реестру №${m * 2 + 1}`,
  });
  add(dayOf(m, 20), OPERATING, "out", rub(payroll * 0.4), {
    counterparty: VENDORS.payroll,
    category: cat("Payroll"),
    description: `Аванс за ${forMonth} по реестру №${m * 2 + 2}`,
  });
  add(dayOf(m, 28), OPERATING, "out", rub(payroll * 0.45 + int(-8_000, 8_000)), {
    counterparty: VENDORS.fns,
    category: cat("Taxes"),
    description: "Единый налоговый платеж (НДФЛ, страховые взносы)",
  });
  if ([0, 3, 6, 9].includes(m)) {
    add(dayOf(m, 27), OPERATING, "out", rub(int(180_000, 260_000)), {
      counterparty: VENDORS.fns,
      category: cat("Taxes"),
      description: "Единый налоговый платеж (НДС, налог на прибыль за квартал)",
    });
  }

  add(dayOf(m, 2), OPERATING, "out", rub(int(68_000, 95_000)), {
    counterparty: VENDORS.yandexCloud,
    category: cat("Cloud & hosting"),
    description: `Yandex Cloud: оплата ресурсов за ${forMonth}`,
  });
  add(dayOf(m, 3), OPERATING, "out", rub(int(24_000, 31_000)), {
    counterparty: VENDORS.selectel,
    category: cat("Cloud & hosting"),
    description: "Selectel: выделенные серверы, пополнение баланса",
  });
  add(dayOf(m, 10), OPERATING, "out", rub(3_900), {
    counterparty: VENDORS.kontur,
    category: cat("Software"),
    description: "Контур.Диадок и Бухгалтерия: абонентская плата",
  });

  // The card is topped up from the operating account and pays foreign SaaS.
  const topUp = rub(int(65_000, 85_000));
  const topUpDate = dayOf(m, 1);
  add(topUpDate, OPERATING, "transfer", topUp, {
    description: "Пополнение корпоративной карты (конвертация RUB→USD)",
    to: { account: CARD, amount: roundMinor(topUp / rateOn(topUpDate)) },
  });
  add(addDays(topUpDate, 1), CARD, "out", usd(int(180, 260) + int(0, 99) / 100), {
    counterparty: VENDORS.aws,
    category: cat("Cloud & hosting"),
    description: "AWS EMEA SARL aws.amazon.com",
  });
  add(dayOf(m, 6), CARD, "out", usd(84), {
    counterparty: VENDORS.github,
    category: cat("Software"),
    description: "GITHUB, INC. SAN FRANCISCO",
  });
  add(dayOf(m, 9), CARD, "out", usd(45), {
    counterparty: VENDORS.figma,
    category: cat("Software"),
    description: "FIGMA MONTHLY RENEWAL",
  });
  add(dayOf(m, 11), CARD, "out", usd(64), {
    counterparty: VENDORS.notion,
    category: cat("Software"),
    description: "NOTION LABS, INC.",
  });
  add(dayOf(m, 15), CARD, "out", usd(int(120, 480) + int(0, 99) / 100), {
    counterparty: VENDORS.openai,
    category: cat("Software"),
    description: "OPENAI *API USAGE",
  });

  add(dayOf(m, 25), OPERATING, "out", rub(int(90, 140) * 1_000), {
    counterparty: VENDORS.petrov,
    category: cat("Contractors"),
    description: `Оплата по договору ГПХ №Д-12 за ${forMonth} (дизайн интерфейсов). НДС не облагается`,
  });
  add(dayOf(m, 24), OPERATING, "out", rub(int(45, 70) * 1_000), {
    counterparty: VENDORS.kim,
    category: cat("Contractors"),
    description: `Оплата по договору №Т-07 за ${forMonth} (тестирование). НДС не облагается`,
  });
  if (chance(0.5)) {
    add(dayOf(m, 18), OPERATING, "out", rub(int(35, 80) * 1_000), {
      counterparty: VENDORS.orlov,
      category: cat("Contractors"),
      description: "Оплата по счету: настройка инфраструктуры. НДС не облагается",
    });
  }

  add(dayOf(m, 1), OPERATING, "out", rub(120_000), {
    counterparty: VENDORS.ladoga,
    category: cat("Office"),
    description: `Арендная плата за ${forMonth}, офис 12, в т.ч. НДС 22%`,
  });
  add(dayOf(m, 12), OPERATING, "out", rub(int(4_200, 6_800)), {
    counterparty: VENDORS.aqua,
    category: cat("Office"),
    description: "Вода и кофе для офиса",
  });
  if (chance(0.25)) {
    add(dayOf(m, int(13, 22)), OPERATING, "out", rub(int(8_000, 25_000)), {
      counterparty: VENDORS.kanc,
      category: cat("Office"),
      description: "Канцтовары и расходные материалы",
    });
  }

  add(dayOf(m, 7), OPERATING, "out", rub(int(30, 60) * 1_000), {
    counterparty: VENDORS.direct,
    category: cat("Marketing"),
    description: "Яндекс Директ: пополнение рекламного кабинета",
  });

  add(lastWorkday(m), OPERATING, "out", rub(2_490), {
    counterparty: VENDORS.bank,
    category: cat("Bank fees"),
    description: "Комиссия за обслуживание счета",
  });
  add(lastWorkday(m), OPERATING, "out", rub(int(18, 46) * 49), {
    counterparty: VENDORS.bank,
    category: cat("Bank fees"),
    description: "Комиссия за платежи в другие банки",
  });
  add(lastWorkday(m), RESERVE, "out", rub(490), {
    counterparty: VENDORS.bank,
    category: cat("Bank fees"),
    description: "Комиссия за обслуживание накопительного счета",
  });
  add(lastWorkday(m), RESERVE, "in", rub(int(17_500, 22_500)), {
    counterparty: VENDORS.bank,
    category: cat("Other income"),
    description: "Выплата процентов на остаток",
  });

  if (chance(0.85)) {
    add(dayOf(m, int(8, 26)), OPERATING, "out", rub(int(1_200, 6_500)), {
      counterparty: VENDORS.courier,
      category: cat("Other"),
      description: "Курьерская доставка документов",
    });
  }
}

add("2026-01-14", CARD, "out", usd(1_470), {
  counterparty: VENDORS.jetbrains,
  category: cat("Software"),
  description: "JETBRAINS ALL PRODUCTS PACK x6 ANNUAL",
});
add("2026-03-19", OPERATING, "out", rub(120_000), {
  counterparty: VENDORS.event,
  category: cat("Marketing"),
  description: "Участие в конференции: стенд и два билета, в т.ч. НДС 22%",
});
// A vendor refund lands in its expense category and reduces that expense.
add("2026-05-14", OPERATING, "in", rub(6_400), {
  counterparty: VENDORS.selectel,
  category: cat("Cloud & hosting"),
  description: "Selectel: возврат неиспользованного остатка",
});

// ---------------------------------------------------------------------------
// Invoices for project work, and their payments
// ---------------------------------------------------------------------------

const invoices: Invoice[] = [];
const hours = (n: number, rate: number, what: string): InvoiceLine => ({
  description: `${what}, часов`,
  quantity: n,
  unitPrice: rub(rate),
  vatRate: 22,
});
const fixed = (amount: number, what: string, vatRate: number | null = 22): InvoiceLine => ({
  description: what,
  quantity: 1,
  unitPrice: rub(amount),
  vatRate,
});

const INVOICES: {
  client: string;
  issued: string;
  terms: number;
  lines: InvoiceLine[];
  payments?: { date: string; share?: number }[];
  draft?: boolean;
  voided?: string;
}[] = [
  { client: CLIENTS.sfera, issued: "2025-10-08", terms: 14, lines: [hours(40, 6_500, "Интеграция с 1С:УТ")], payments: [{ date: "2025-10-20" }] },
  { client: CLIENTS.polaris, issued: "2025-11-12", terms: 14, lines: [fixed(490_000, "Внедрение модуля маршрутизации")], payments: [{ date: "2025-11-28" }] },
  { client: CLIENTS.granit, issued: "2025-12-03", terms: 21, lines: [hours(64, 6_500, "Доработка личного кабинета")], payments: [{ date: "2025-12-24" }] },
  {
    client: CLIENTS.briz,
    issued: "2026-01-20",
    terms: 14,
    lines: [fixed(190_000, "Аудит архитектуры и отчет"), hours(10, 6_500, "Консультации")],
    payments: [{ date: "2026-02-06" }],
  },
  {
    client: CLIENTS.meridian,
    issued: "2026-02-16",
    terms: 30,
    lines: [hours(120, 6_500, "Разработка API для партнеров")],
    payments: [{ date: "2026-03-05", share: 0.4 }, { date: "2026-03-30" }],
  },
  { client: CLIENTS.okto, issued: "2026-03-18", terms: 21, lines: [fixed(560_000, "MVP мобильного приложения, этап 1")], payments: [{ date: "2026-04-10" }] },
  {
    client: CLIENTS.atlas,
    issued: "2026-04-14",
    terms: 14,
    lines: [hours(80, 6_500, "Интеграция с МИС")],
    payments: [{ date: "2026-05-12", share: 0.4 }],
  },
  { client: CLIENTS.sfera, issued: "2026-05-19", terms: 14, lines: [fixed(340_000, "Модуль программы лояльности")], payments: [{ date: "2026-06-02" }] },
  { client: CLIENTS.veter, issued: "2026-06-22", terms: 14, lines: [hours(56, 6_500, "Миграция на облачную инфраструктуру")], payments: [{ date: "2026-07-08" }] },
  { client: CLIENTS.briz, issued: "2026-06-30", terms: 14, lines: [fixed(95_000, "Доработка медиатеки")], voided: "2026-07-01" },
  { client: CLIENTS.polaris, issued: "2026-07-15", terms: 30, lines: [fixed(690_000, "Модуль складской аналитики")] },
  {
    client: CLIENTS.yasen,
    issued: "2026-08-10",
    terms: 14,
    lines: [fixed(240_000, "Лицензия на ПО на 12 месяцев (НДС не облагается, пп. 26 п. 2 ст. 149 НК РФ)", null)],
    payments: [{ date: "2026-08-25" }],
  },
  { client: CLIENTS.granit, issued: "2026-08-28", terms: 14, lines: [hours(72, 6_500, "Разработка модуля отчетности")] },
  {
    client: CLIENTS.meridian,
    issued: "2026-09-08",
    terms: 30,
    lines: [fixed(620_000, "Разработка API, этап 2")],
    payments: [{ date: "2026-09-22", share: 0.35 }],
  },
  { client: CLIENTS.okto, issued: "2026-09-21", terms: 14, lines: [hours(40, 6_500, "Поддержка и доработки")] },
  { client: CLIENTS.atlas, issued: "2026-09-25", terms: 14, lines: [fixed(410_000, "Интеграция с МИС, этап 2")], draft: true },
];

INVOICES.sort((a, b) => a.issued.localeCompare(b.issued)).forEach((spec, index) => {
  const number = `INV-${String(index + 1).padStart(4, "0")}`;
  const invoice: Invoice = {
    id: `inv_${String(index + 1).padStart(4, "0")}`,
    number,
    counterpartyId: spec.client,
    issueDate: spec.issued,
    dueDate: addDays(spec.issued, spec.terms),
    currency: "RUB",
    lines: spec.lines,
    notes: "Оплата по счету означает согласие с условиями договора. Срок оплаты указан в счете.",
    categoryId: cat("Services"),
    sentAt: spec.draft ? null : `${spec.issued}T10:00:00.000Z`,
    voidedAt: spec.voided ? `${spec.voided}T12:00:00.000Z` : null,
    createdAt: `${spec.issued}T09:30:00.000Z`,
  };
  invoices.push(invoice);
  const total = invoiceTotals(invoice.lines).total;
  let paid = 0;
  for (const payment of spec.payments ?? []) {
    const amount = payment.share ? Math.round((total * payment.share) / 10_000) * 10_000 : total - paid;
    paid += amount;
    add(payment.date, OPERATING, "in", amount, {
      counterparty: spec.client,
      category: cat("Services"),
      invoiceId: invoice.id,
      description: `Оплата по счету ${number} от ${ruDate(spec.issued)}, в т.ч. НДС`,
    });
  }
});

// ---------------------------------------------------------------------------
// Ordering, ids, the reserve sweep, review queue and reconciliation
// ---------------------------------------------------------------------------

const order = () =>
  transactions.sort((a, b) => a.date.localeCompare(b.date) || a.accountId.localeCompare(b.accountId) || a.description.localeCompare(b.description));

// Whenever the operating account would dip under 400 000 ₽, a million comes over from the reserve the day before.
for (let guard = 0; guard < 24; guard++) {
  order();
  let balance = accounts[0].openingBalance;
  let dip: string | null = null;
  for (const t of transactions) {
    if (t.accountId === OPERATING) balance += t.direction === "in" ? t.amount : -t.amount;
    else if (t.transferAccountId === OPERATING) balance += t.transferAmount!;
    if (balance < rub(400_000)) {
      dip = t.date;
      break;
    }
  }
  if (!dip) break;
  add(addDays(dip, -1), RESERVE, "transfer", rub(1_000_000), {
    description: "Перевод с накопительного счета на расчетный",
    to: { account: OPERATING, amount: rub(1_000_000) },
  });
}
order();
transactions.forEach((t, i) => (t.id = `tx_${String(i + 1).padStart(5, "0")}`));

// The newest bank lines came in from a statement import and still need a category.
const reviewable = transactions
  .filter((t) => t.direction !== "transfer" && t.invoiceId === null && t.counterpartyId !== VENDORS.payroll)
  .slice(-REVIEW_COUNT);
for (const t of reviewable) {
  t.categoryId = null;
  t.source = "import";
  t.bankMemo = t.description;
  if (t.accountId === CARD) t.counterpartyId = null;
}

const reconciledUntil = addDays(AS_OF, -30);
for (const t of transactions) {
  t.reconciled = t.date <= reconciledUntil && (t.categoryId !== null || t.direction === "transfer");
}

const data: BooksData = {
  version: 1,
  asOf: AS_OF,
  book,
  accounts,
  categories,
  counterparties,
  transactions,
  invoices,
};

await fs.mkdir(path.dirname(OUT), { recursive: true });
await fs.writeFile(OUT, `${JSON.stringify(data, null, 2)}\n`, "utf-8");
const sweeps = transactions.filter((t) => t.accountId === RESERVE && t.direction === "transfer").length;
console.log(
  `Wrote ${path.relative(process.cwd(), OUT)}: ${accounts.length} accounts, ${categories.length} categories, ` +
    `${counterparties.length} counterparties, ${transactions.length} transactions ` +
    `(${reviewable.length} to review, ${sweeps} reserve sweeps), ${invoices.length} invoices; ${START} to ${AS_OF}`,
);
