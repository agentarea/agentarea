/**
 * Generates `data/crm.json`: a deterministic B2B sales CRM dataset.
 *
 * Every random choice comes from one PRNG with a fixed seed and every date is
 * relative to a fixed `AS_OF`, so running the script twice yields the same file.
 */
import fs from "node:fs/promises";
import path from "node:path";
import type {
  Activity,
  ActivityType,
  Company,
  CompanySize,
  Contact,
  CrmData,
  Currency,
  Deal,
  Owner,
  Pipeline,
  StageVisit,
} from "../shared/crm.ts";

const SEED = 0xc0ffee_26;
const AS_OF = Date.parse("2026-10-05T07:00:00.000Z");
const MINUTE = 60_000;
const HOUR = 60 * MINUTE;
const DAY = 24 * HOUR;
const OUT = path.join(import.meta.dirname, "..", "data", "crm.json");

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
const pick = <T>(items: readonly T[]): T => items[Math.floor(random() * items.length)];
const chance = (p: number) => random() < p;
function weighted<T extends string>(weights: Record<T, number>): T {
  const entries = Object.entries(weights) as [T, number][];
  let roll = random() * entries.reduce((sum, [, w]) => sum + w, 0);
  for (const [value, weight] of entries) {
    roll -= weight;
    if (roll <= 0) return value;
  }
  return entries[entries.length - 1][0];
}
function shuffle<T>(items: T[]): T[] {
  for (let i = items.length - 1; i > 0; i--) {
    const j = Math.floor(random() * (i + 1));
    [items[i], items[j]] = [items[j], items[i]];
  }
  return items;
}
const pad = (n: number, width = 3) => String(n).padStart(width, "0");
const iso = (ms: number) => new Date(ms).toISOString();

/** Moves a timestamp into weekday Moscow working hours (06:00–15:00 UTC). */
function workingHours(ms: number): number {
  const date = new Date(ms);
  const hour = date.getUTCHours();
  if (hour < 6) date.setUTCHours(6 + int(0, 2), int(0, 59));
  if (hour >= 15) {
    date.setUTCDate(date.getUTCDate() + 1);
    date.setUTCHours(6 + int(0, 3), int(0, 59));
  }
  const weekday = date.getUTCDay();
  if (weekday === 6) date.setUTCDate(date.getUTCDate() + 2);
  if (weekday === 0) date.setUTCDate(date.getUTCDate() + 1);
  return date.getTime();
}
/** A working-hours moment that has already happened. */
const past = (ms: number) => Math.min(workingHours(ms), AS_OF - int(20, 90) * MINUTE);

// ---------------------------------------------------------------------------
// Reference data
// ---------------------------------------------------------------------------

const OWNERS: Owner[] = [
  { id: "own_01", name: "Anna Sokolova", handle: "anna", title: "Head of Sales", email: "anna.sokolova@meridian.ru", kind: "human", platformId: null },
  { id: "own_02", name: "Dmitry Volkov", handle: "dmitry", title: "Account Executive", email: "dmitry.volkov@meridian.ru", kind: "human", platformId: null },
  { id: "own_03", name: "Elena Petrova", handle: "elena", title: "Account Executive", email: "elena.petrova@meridian.ru", kind: "human", platformId: null },
  { id: "own_04", name: "Ivan Kuznetsov", handle: "ivan", title: "Sales Development Rep", email: "ivan.kuznetsov@meridian.ru", kind: "human", platformId: null },
  { id: "own_05", name: "Scout", handle: "scout", title: "AI sales agent", email: "scout@meridian.ru", kind: "agent", platformId: null },
];
const HUMANS = OWNERS.filter((o) => o.kind === "human");
const AGENT = OWNERS.find((o) => o.kind === "agent")!;

const PIPELINE: Pipeline = {
  id: "default",
  name: "Sales pipeline",
  stages: [
    { id: "lead", name: "Lead in", probability: 0.1, rottenAfterDays: 7, outcome: null },
    { id: "qualified", name: "Qualified", probability: 0.25, rottenAfterDays: 10, outcome: null },
    { id: "proposal", name: "Proposal sent", probability: 0.5, rottenAfterDays: 14, outcome: null },
    { id: "negotiation", name: "Negotiation", probability: 0.75, rottenAfterDays: 10, outcome: null },
    { id: "won", name: "Won", probability: 1, rottenAfterDays: null, outcome: "won" },
    { id: "lost", name: "Lost", probability: 0, rottenAfterDays: null, outcome: "lost" },
  ],
};
const OPEN_STAGES = PIPELINE.stages.filter((s) => s.outcome === null);

const LOST_REASONS = [
  "Price too high",
  "Chose a competitor",
  "No budget this year",
  "Went silent",
  "Timing — revisit next quarter",
  "Missing integration",
];
const SOURCES = ["Inbound — website", "Outbound", "Referral", "Partner", "Trade show", "Webinar"];

type CompanySeed = [name: string, domain: string, industry: string, city: string, currency: Currency, phone: string];
const COMPANIES: CompanySeed[] = [
  ["Volga Logistics", "volgalog.ru", "Logistics", "Nizhny Novgorod", "RUB", "+7"],
  ["Kama Freight", "kamafreight.ru", "Logistics", "Kazan", "RUB", "+7"],
  ["Baltic Cold Chain", "balticcold.ru", "Cold storage", "Saint Petersburg", "RUB", "+7"],
  ["Sibir Agro", "sibiragro.ru", "Agriculture", "Novosibirsk", "RUB", "+7"],
  ["Neva Retail Group", "nevaretail.ru", "Retail", "Saint Petersburg", "RUB", "+7"],
  ["Tver Pharma Distribution", "tverpharma.ru", "Pharma distribution", "Tver", "RUB", "+7"],
  ["Altai Foods", "altaifoods.ru", "Food production", "Barnaul", "RUB", "+7"],
  ["Krasny Bor Furniture", "krasnybor.ru", "Manufacturing", "Yekaterinburg", "RUB", "+7"],
  ["Ural Metal Supply", "uralmetal.ru", "Metals wholesale", "Chelyabinsk", "RUB", "+7"],
  ["Don Agroholding", "donagro.ru", "Agriculture", "Rostov-on-Don", "RUB", "+7"],
  ["Vector Electronics", "vector-el.ru", "Electronics distribution", "Moscow", "RUB", "+7"],
  ["Polar Fisheries", "polarfish.ru", "Food production", "Murmansk", "RUB", "+7"],
  ["Kazan Auto Parts", "kazanautoparts.ru", "Automotive", "Kazan", "RUB", "+7"],
  ["Stolitsa Office Supply", "stolitsa-office.ru", "Wholesale", "Moscow", "RUB", "+7"],
  ["Tula Packaging", "tulapack.ru", "Manufacturing", "Tula", "RUB", "+7"],
  ["Samara Building Materials", "samarabm.ru", "Construction materials", "Samara", "RUB", "+7"],
  ["Rostov Grain Terminal", "rostovgrain.ru", "Ports & terminals", "Rostov-on-Don", "RUB", "+7"],
  ["Yug Wine Distribution", "yugwine.ru", "Beverage distribution", "Krasnodar", "RUB", "+7"],
  ["Primorye Port Services", "primport.ru", "Ports & terminals", "Vladivostok", "RUB", "+7"],
  ["Omsk Chemicals", "omskchem.ru", "Chemicals", "Omsk", "RUB", "+7"],
  ["Perm Paper Mill", "permpaper.ru", "Manufacturing", "Perm", "RUB", "+7"],
  ["Caspian Trade FZE", "caspiantrade.ae", "Wholesale", "Dubai", "USD", "+971"],
  ["Ararat Logistics", "araratlog.am", "Logistics", "Yerevan", "USD", "+374"],
  ["Steppe Retail", "stepperetail.kz", "Retail", "Almaty", "USD", "+7"],
  ["Danube Distribution", "danubedist.rs", "Wholesale", "Belgrade", "USD", "+381"],
];
const SIZES: Record<CompanySize, number> = { "1-10": 0, "11-50": 3, "51-200": 8, "201-500": 7, "501-1000": 4, "1000+": 3 };

const FIRST_MALE = ["Sergey", "Alexey", "Andrey", "Pavel", "Mikhail", "Nikolai", "Roman", "Oleg", "Artem", "Igor", "Konstantin", "Maxim"];
const FIRST_FEMALE = ["Olga", "Natalia", "Irina", "Tatiana", "Maria", "Ekaterina", "Svetlana", "Yulia", "Daria", "Ksenia", "Alina", "Vera"];
const LAST_NAMES = [
  "Ivanov", "Smirnov", "Popov", "Lebedev", "Kozlov", "Novikov", "Morozov", "Pavlov", "Fedorov", "Orlov", "Belov",
  "Zaitsev", "Medvedev", "Egorov", "Nikitin", "Sorokin", "Gusev", "Tarasov", "Belyaev", "Komarov", "Vinogradov",
];
const FOREIGN_NAMES: Record<string, readonly string[]> = {
  "+971": ["Omar Haddad", "Layla Nasser", "Karim Aziz", "Rania Saleh"],
  "+374": ["Armen Petrosyan", "Ani Hakobyan", "Davit Sargsyan", "Lilit Grigoryan"],
  "+7": ["Aidar Nurlanov", "Dana Seitkali", "Yerlan Abenov", "Aigerim Tulegen"],
  "+381": ["Marko Jovanovic", "Ana Petrovic", "Nikola Ilic", "Jelena Markovic"],
};
const TITLES = [
  "CEO", "COO", "CFO", "Head of Logistics", "Procurement Director", "IT Director", "Warehouse Manager",
  "Head of Supply Chain", "Commercial Director", "Operations Manager",
];
const PRODUCTS = [
  () => `WMS rollout, ${int(2, 6)} warehouses`,
  () => "Route optimization module",
  () => "Analytics add-on",
  () => `Pilot, ${pick([25, 40, 50, 80])} seats`,
  () => "Annual license renewal",
  () => "Yard management",
  () => "1C integration",
  () => "Premium support upgrade",
  () => "Fleet telematics bundle",
  () => "Demand forecasting",
];

const ACTIVITY_SUBJECTS: Record<ActivityType, readonly string[]> = {
  call: ["Discovery call", "Follow-up call", "Pricing call with procurement", "Check-in call", "Call about pilot results"],
  email: ["Sent product overview", "Sent commercial proposal", "Shared customer case study", "Sent revised pricing", "Follow-up email"],
  meeting: ["Demo for the operations team", "On-site warehouse visit", "Negotiation meeting", "Kick-off meeting", "Security review session"],
  task: ["Prepare ROI estimate", "Send contract draft", "Prepare pilot plan", "Get legal sign-off", "Update proposal after feedback"],
  note: ["Budget confirmed", "Decision maker identified", "Competitor in the deal", "Procurement process notes", "Requirements summary"],
};
const NOTE_BODIES = [
  "Budget is approved for Q4; final sign-off sits with the CFO.",
  "They run two warehouses on spreadsheets today and want a single stock view.",
  "Competitor is in the deal with a lower price but no 1C integration.",
  "Procurement needs three quotes and a security questionnaire.",
  "Main pain: late deliveries and no visibility into picking times.",
  "Asked for a reference customer in the same industry.",
];

// ---------------------------------------------------------------------------
// Companies and contacts
// ---------------------------------------------------------------------------

const companies: Company[] = [];
const contacts: Contact[] = [];
const usedNames = new Set<string>();

function phoneFor(prefix: string): string {
  const digits = (n: number) => Array.from({ length: n }, () => int(0, 9)).join("");
  switch (prefix) {
    case "+971":
      return `+971 50 ${digits(3)} ${digits(4)}`;
    case "+374":
      return `+374 9${int(1, 9)} ${digits(3)} ${digits(3)}`;
    case "+381":
      return `+381 6${int(0, 9)} ${digits(3)} ${digits(4)}`;
    default:
      return `+7 9${digits(2)} ${digits(3)}-${digits(2)}-${digits(2)}`;
  }
}

function personName(prefix: string, foreign: boolean): string {
  for (;;) {
    let name: string;
    if (foreign) {
      name = pick(FOREIGN_NAMES[prefix]);
    } else if (chance(0.5)) {
      name = `${pick(FIRST_MALE)} ${pick(LAST_NAMES)}`;
    } else {
      name = `${pick(FIRST_FEMALE)} ${pick(LAST_NAMES)}a`;
    }
    if (!usedNames.has(name)) {
      usedNames.add(name);
      return name;
    }
  }
}

for (const [name, domain, industry, city, currency, prefix] of COMPANIES) {
  const company: Company = {
    id: `cmp_${pad(companies.length + 1)}`,
    name,
    domain,
    industry,
    size: weighted(SIZES),
    city,
    ownerId: pick(HUMANS).id,
    createdAt: "",
  };
  companies.push(company);
  const titles = shuffle([...TITLES]);
  for (let i = 0; i < 2; i++) {
    const person = personName(prefix, currency === "USD");
    contacts.push({
      id: `ct_${pad(contacts.length + 1)}`,
      companyId: company.id,
      name: person,
      title: titles[i],
      email: `${person.toLowerCase().replace(" ", ".")}@${domain}`,
      phone: phoneFor(prefix),
      ownerId: company.ownerId,
      createdAt: "",
    });
  }
}
const currencyOf = new Map(COMPANIES.map(([name, , , , currency]) => [name, currency]));

// ---------------------------------------------------------------------------
// Deals, their stage history and activities
// ---------------------------------------------------------------------------

type Outcome = (typeof OPEN_STAGES)[number]["id"] | "won" | "lost";
const OUTCOMES: Outcome[] = shuffle([
  ...Array<Outcome>(8).fill("lead"),
  ...Array<Outcome>(8).fill("qualified"),
  ...Array<Outcome>(7).fill("proposal"),
  ...Array<Outcome>(6).fill("negotiation"),
  ...Array<Outcome>(9).fill("won"),
  ...Array<Outcome>(7).fill("lost"),
]);

const deals: Deal[] = [];
const activities: Omit<Activity, "id">[] = [];
const companyOrder = shuffle([...companies]);
let wonThisMonth = 0;
// What the open deals have lined up next: most are on track, some slipped, some have nothing.
const OPEN_COUNT = OUTCOMES.filter((o) => o !== "won" && o !== "lost").length;
const NEXT_PLANS = shuffle([
  ...Array<"overdue">(8).fill("overdue"),
  ...Array<"none">(5).fill("none"),
  ...Array<"upcoming">(OPEN_COUNT - 13).fill("upcoming"),
]);

function activityType(): ActivityType {
  return weighted<ActivityType>({ call: 30, email: 30, meeting: 15, note: 15, task: 10 });
}

OUTCOMES.forEach((outcome, index) => {
  const company = companyOrder[index % companyOrder.length];
  const currency = currencyOf.get(company.name)!;
  const people = contacts.filter((c) => c.companyId === company.id);
  const value =
    currency === "USD"
      ? Math.round(Math.exp(9 + random() * 2.4) / 500) * 500
      : Math.round(Math.exp(12.6 + random() * 3.6) / 10_000) * 10_000;
  const closed = outcome === "won" || outcome === "lost";

  // Walk the stages backwards from now (open) or from the close (won/lost).
  let closedAt: number | null = null;
  if (closed) {
    const thisMonth = outcome === "won" && wonThisMonth < 2;
    if (thisMonth) wonThisMonth += 1;
    closedAt = thisMonth ? AS_OF - (wonThisMonth === 1 ? 3.8 : 2.9) * DAY : past(AS_OF - int(5, 120) * DAY);
  }
  const reached = outcome === "won" ? 3 : outcome === "lost" ? Number(weighted({ 0: 3, 1: 3, 2: 3, 3: 2 })) : OPEN_STAGES.findIndex((s) => s.id === outcome);
  const visits: StageVisit[] = [];
  let cursor = closedAt ?? AS_OF;
  if (closedAt !== null) visits.unshift({ stageId: outcome, enteredAt: iso(closedAt), leftAt: null });
  for (let i = reached; i >= 0; i--) {
    const stage = OPEN_STAGES[i];
    const current = !closed && i === reached;
    const days = current
      ? chance(0.22)
        ? stage.rottenAfterDays! + int(1, 16)
        : int(0, stage.rottenAfterDays! - 1)
      : int(2, 15);
    const enteredAt = Math.min(past(cursor - days * DAY - int(0, 300) * MINUTE), cursor - HOUR);
    visits.unshift({ stageId: stage.id, enteredAt: iso(enteredAt), leftAt: current ? null : iso(cursor) });
    cursor = enteredAt;
  }
  const createdAt = Date.parse(visits[0].enteredAt);

  const ownerId =
    (outcome === "lead" || outcome === "qualified") && chance(0.4) ? AGENT.id : chance(0.8) ? company.ownerId : pick(HUMANS).id;
  const dealContacts = people.slice(0, chance(0.45) ? 2 : 1);
  const deal: Deal = {
    id: `deal_${pad(deals.length + 1)}`,
    title: `${company.name.split(" ").slice(0, 2).join(" ")} — ${pick(PRODUCTS)()}`,
    pipelineId: PIPELINE.id,
    stageId: closed ? outcome : OPEN_STAGES[reached].id,
    status: outcome === "won" ? "won" : outcome === "lost" ? "lost" : "open",
    lostReason: outcome === "lost" ? pick(LOST_REASONS) : null,
    companyId: company.id,
    contactIds: dealContacts.map((c) => c.id),
    ownerId,
    value,
    currency,
    expectedCloseDate: iso(closedAt ?? AS_OF + int(-6, 70) * DAY).slice(0, 10),
    source: weighted({
      "Inbound — website": 26,
      Outbound: ownerId === AGENT.id ? 60 : 22,
      Referral: 16,
      Partner: 12,
      "Trade show": 10,
      Webinar: 8,
    }),
    createdAt: iso(createdAt),
    updatedAt: "",
    closedAt: closedAt === null ? null : iso(closedAt),
    stageHistory: visits,
  };
  deals.push(deal);

  // Done work along the deal's history.
  const end = closedAt ?? AS_OF;
  const doneCount = Number(weighted({ 1: 1, 2: 3, 3: 4, 4: 2 }));
  for (let i = 0; i < doneCount; i++) {
    const type = deal.ownerId === AGENT.id ? "email" : activityType();
    const at = past(createdAt + ((i + random()) / doneCount) * (end - createdAt));
    activities.push({
      type,
      subject: pick(ACTIVITY_SUBJECTS[type]),
      note: type === "note" || chance(0.25) ? pick(NOTE_BODIES) : "",
      dueAt: iso(at),
      done: true,
      doneAt: iso(Math.min(at + int(5, 90) * MINUTE, AS_OF)),
      dealId: deal.id,
      contactId: type === "note" ? null : pick(dealContacts).id,
      ownerId: deal.ownerId,
      createdAt: iso(Math.max(createdAt, at - int(0, 3) * DAY)),
    });
  }

  if (!closed) {
    const plan = NEXT_PLANS.pop()!;
    if (plan !== "none") {
      const type = deal.ownerId === AGENT.id ? "email" : weighted<ActivityType>({ call: 35, email: 20, meeting: 25, task: 20, note: 0 });
      const dueAt =
        plan === "upcoming"
          ? workingHours(AS_OF + int(2, 240) * HOUR)
          : Math.min(past(AS_OF - int(1, 9) * DAY), AS_OF - DAY - int(1, 4) * HOUR);
      activities.push({
        type,
        subject: pick(ACTIVITY_SUBJECTS[type]),
        note: "",
        dueAt: iso(dueAt),
        done: false,
        doneAt: null,
        dealId: deal.id,
        contactId: type === "task" ? null : pick(dealContacts).id,
        ownerId: deal.ownerId,
        createdAt: iso(Math.max(createdAt, Math.min(dueAt, AS_OF) - int(1, 5) * DAY)),
      });
    }
  }
});

// A few touches on contacts outside any deal.
for (let i = 0; i < 12; i++) {
  const contact = pick(contacts);
  const type = pick<ActivityType>(["call", "email", "note"]);
  const at = past(AS_OF - int(1, 40) * DAY);
  activities.push({
    type,
    subject: type === "note" ? "Met at the logistics expo" : type === "call" ? "Intro call" : "Sent company overview",
    note: type === "note" ? "Interested in route optimization next year; no budget now." : "",
    dueAt: iso(at),
    done: true,
    doneAt: iso(at),
    dealId: null,
    contactId: contact.id,
    ownerId: contact.ownerId,
    createdAt: iso(at),
  });
}

const sortedActivities: Activity[] = activities
  .toSorted((a, b) => a.dueAt.localeCompare(b.dueAt))
  .map((activity, i) => ({ id: `act_${pad(i + 1, 4)}`, ...activity }));

for (const deal of deals) {
  const touched = sortedActivities
    .filter((a) => a.dealId === deal.id)
    .map((a) => (a.doneAt ?? a.createdAt))
    .concat(deal.stageHistory.map((v) => v.enteredAt))
    .filter((at) => Date.parse(at) <= AS_OF);
  deal.updatedAt = touched.toSorted().at(-1)!;
}
for (const company of companies) {
  const first = deals
    .filter((d) => d.companyId === company.id)
    .map((d) => Date.parse(d.createdAt))
    .reduce((min, at) => Math.min(min, at), AS_OF - 30 * DAY);
  company.createdAt = iso(past(first - int(1, 20) * DAY));
}
for (const contact of contacts) {
  const company = companies.find((c) => c.id === contact.companyId)!;
  contact.createdAt = iso(Math.min(Date.parse(company.createdAt) + int(0, 3) * HOUR, AS_OF));
}

const data: CrmData = {
  version: 1,
  asOf: iso(AS_OF),
  account: { name: "Meridian Systems", baseCurrency: "RUB" },
  fxRates: { RUB: 1, USD: 92 },
  lostReasons: LOST_REASONS,
  sources: SOURCES,
  owners: OWNERS,
  pipelines: [PIPELINE],
  companies,
  contacts,
  deals,
  activities: sortedActivities,
};

await fs.mkdir(path.dirname(OUT), { recursive: true });
await fs.writeFile(OUT, `${JSON.stringify(data, null, 2)}\n`, "utf-8");
const byStatus = (status: Deal["status"]) => deals.filter((d) => d.status === status).length;
const open = sortedActivities.filter((a) => !a.done);
console.log(
  `Wrote ${path.relative(process.cwd(), OUT)}: ${companies.length} companies, ${contacts.length} contacts, ` +
    `${deals.length} deals (${byStatus("open")} open, ${byStatus("won")} won, ${byStatus("lost")} lost), ` +
    `${sortedActivities.length} activities (${open.length} open, ${open.filter((a) => Date.parse(a.dueAt) < AS_OF).length} overdue)`,
);
