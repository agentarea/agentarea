import type { Database } from "bun:sqlite";
import { insertRows, type Row, type Rows, type Table } from "@kit/store/rows.ts";
import type { Migration } from "@kit/store/store.ts";
import demo from "../data/crm.json" with { type: "json" };
import type {
  ActivityType,
  CompanySize,
  CrmData,
  Currency,
  DealStatus,
  OwnerKind,
  Pipeline,
  Stage,
} from "../shared/crm.ts";

export const DB_FILE = "crm.sqlite";

/** Migration `i` brings the schema to version `i + 1`. Never edit one that has shipped: append. */
export const MIGRATIONS: Migration[] = [
  (db) =>
    db.run(`
      CREATE TABLE account (
        id            INTEGER PRIMARY KEY CHECK (id = 1),
        name          TEXT NOT NULL,
        base_currency TEXT NOT NULL CHECK (base_currency IN ('RUB', 'USD')),
        as_of         TEXT NOT NULL
      );
      CREATE TABLE fx_rates (
        currency TEXT PRIMARY KEY CHECK (currency IN ('RUB', 'USD')),
        rate     REAL NOT NULL CHECK (rate > 0)
      );
      CREATE TABLE lost_reasons (
        position INTEGER PRIMARY KEY,
        reason   TEXT NOT NULL
      );
      CREATE TABLE sources (
        position INTEGER PRIMARY KEY,
        name     TEXT NOT NULL
      );
      CREATE TABLE owners (
        id    TEXT PRIMARY KEY,
        name  TEXT NOT NULL,
        title TEXT NOT NULL,
        email TEXT NOT NULL,
        kind  TEXT NOT NULL CHECK (kind IN ('human', 'agent'))
      );
      CREATE TABLE pipelines (
        id   TEXT PRIMARY KEY,
        name TEXT NOT NULL
      );
      CREATE TABLE stages (
        pipeline_id       TEXT NOT NULL REFERENCES pipelines (id),
        id                TEXT NOT NULL,
        position          INTEGER NOT NULL,
        name              TEXT NOT NULL,
        probability       REAL NOT NULL CHECK (probability BETWEEN 0 AND 1),
        rotten_after_days INTEGER,
        outcome           TEXT CHECK (outcome IN ('won', 'lost')),
        PRIMARY KEY (pipeline_id, id)
      );
      CREATE TABLE companies (
        id         TEXT PRIMARY KEY,
        name       TEXT NOT NULL,
        domain     TEXT NOT NULL,
        industry   TEXT NOT NULL,
        size       TEXT CHECK (size IN ('1-10', '11-50', '51-200', '201-500', '501-1000', '1000+')),
        city       TEXT NOT NULL,
        owner_id   TEXT NOT NULL REFERENCES owners (id),
        created_at TEXT NOT NULL
      );
      CREATE INDEX companies_name ON companies (name COLLATE NOCASE);
      CREATE INDEX companies_owner ON companies (owner_id);
      CREATE TABLE contacts (
        id         TEXT PRIMARY KEY,
        company_id TEXT REFERENCES companies (id),
        name       TEXT NOT NULL,
        title      TEXT NOT NULL,
        email      TEXT NOT NULL,
        phone      TEXT NOT NULL,
        owner_id   TEXT NOT NULL REFERENCES owners (id),
        created_at TEXT NOT NULL
      );
      CREATE INDEX contacts_company ON contacts (company_id);
      CREATE INDEX contacts_email ON contacts (email COLLATE NOCASE);
      CREATE TABLE deals (
        id                  TEXT PRIMARY KEY,
        title               TEXT NOT NULL,
        pipeline_id         TEXT NOT NULL,
        stage_id            TEXT NOT NULL,
        status              TEXT NOT NULL CHECK (status IN ('open', 'won', 'lost')),
        lost_reason         TEXT,
        company_id          TEXT REFERENCES companies (id),
        owner_id            TEXT NOT NULL REFERENCES owners (id),
        value               REAL NOT NULL CHECK (value >= 0),
        currency            TEXT NOT NULL CHECK (currency IN ('RUB', 'USD')),
        expected_close_date TEXT,
        source              TEXT NOT NULL,
        created_at          TEXT NOT NULL,
        updated_at          TEXT NOT NULL,
        closed_at           TEXT,
        FOREIGN KEY (pipeline_id, stage_id) REFERENCES stages (pipeline_id, id)
      );
      CREATE INDEX deals_stage ON deals (pipeline_id, stage_id);
      CREATE INDEX deals_status ON deals (status);
      CREATE INDEX deals_owner ON deals (owner_id);
      CREATE INDEX deals_company ON deals (company_id);
      CREATE TABLE deal_contacts (
        deal_id    TEXT NOT NULL REFERENCES deals (id),
        position   INTEGER NOT NULL,
        contact_id TEXT NOT NULL REFERENCES contacts (id),
        PRIMARY KEY (deal_id, position)
      );
      CREATE INDEX deal_contacts_contact ON deal_contacts (contact_id);
      CREATE TABLE stage_visits (
        deal_id    TEXT NOT NULL REFERENCES deals (id),
        position   INTEGER NOT NULL,
        stage_id   TEXT NOT NULL,
        entered_at TEXT NOT NULL,
        left_at    TEXT,
        PRIMARY KEY (deal_id, position)
      );
      CREATE TABLE activities (
        id         TEXT PRIMARY KEY,
        type       TEXT NOT NULL CHECK (type IN ('call', 'email', 'meeting', 'task', 'note')),
        subject    TEXT NOT NULL,
        note       TEXT NOT NULL,
        due_at     TEXT NOT NULL,
        done       INTEGER NOT NULL CHECK (done IN (0, 1)),
        done_at    TEXT,
        deal_id    TEXT REFERENCES deals (id),
        contact_id TEXT REFERENCES contacts (id),
        owner_id   TEXT NOT NULL REFERENCES owners (id),
        created_at TEXT NOT NULL,
        CHECK (deal_id IS NOT NULL OR contact_id IS NOT NULL)
      );
      CREATE INDEX activities_deal ON activities (deal_id, done, due_at);
      CREATE INDEX activities_contact ON activities (contact_id);
    `),
];

export const TABLES: Table[] = [
  { name: "account", columns: ["id", "name", "base_currency", "as_of"], key: ["id"] },
  { name: "fx_rates", columns: ["currency", "rate"], key: ["currency"] },
  { name: "lost_reasons", columns: ["position", "reason"], key: ["position"], orderBy: "position" },
  { name: "sources", columns: ["position", "name"], key: ["position"], orderBy: "position" },
  { name: "owners", columns: ["id", "name", "title", "email", "kind"], key: ["id"] },
  { name: "pipelines", columns: ["id", "name"], key: ["id"] },
  {
    name: "stages",
    columns: ["pipeline_id", "id", "position", "name", "probability", "rotten_after_days", "outcome"],
    key: ["pipeline_id", "id"],
    orderBy: "pipeline_id, position",
  },
  { name: "companies", columns: ["id", "name", "domain", "industry", "size", "city", "owner_id", "created_at"], key: ["id"] },
  { name: "contacts", columns: ["id", "company_id", "name", "title", "email", "phone", "owner_id", "created_at"], key: ["id"] },
  {
    name: "deals",
    columns: [
      "id", "title", "pipeline_id", "stage_id", "status", "lost_reason", "company_id", "owner_id", "value", "currency",
      "expected_close_date", "source", "created_at", "updated_at", "closed_at",
    ],
    key: ["id"],
  },
  { name: "deal_contacts", columns: ["deal_id", "position", "contact_id"], key: ["deal_id", "position"], orderBy: "deal_id, position" },
  {
    name: "stage_visits",
    columns: ["deal_id", "position", "stage_id", "entered_at", "left_at"],
    key: ["deal_id", "position"],
    orderBy: "deal_id, position",
  },
  {
    name: "activities",
    columns: ["id", "type", "subject", "note", "due_at", "done", "done_at", "deal_id", "contact_id", "owner_id", "created_at"],
    key: ["id"],
  },
];

export function toRows(data: CrmData): Rows {
  return {
    account: [{ id: 1, name: data.account.name, base_currency: data.account.baseCurrency, as_of: data.asOf }],
    fx_rates: Object.entries(data.fxRates).map(([currency, rate]) => ({ currency, rate })),
    lost_reasons: data.lostReasons.map((reason, position) => ({ position, reason })),
    sources: data.sources.map((name, position) => ({ position, name })),
    owners: data.owners.map((o) => ({ id: o.id, name: o.name, title: o.title, email: o.email, kind: o.kind })),
    pipelines: data.pipelines.map((p) => ({ id: p.id, name: p.name })),
    stages: data.pipelines.flatMap((p) =>
      p.stages.map((s, position) => ({
        pipeline_id: p.id, id: s.id, position, name: s.name, probability: s.probability,
        rotten_after_days: s.rottenAfterDays, outcome: s.outcome,
      })),
    ),
    companies: data.companies.map((c) => ({
      id: c.id, name: c.name, domain: c.domain, industry: c.industry, size: c.size, city: c.city, owner_id: c.ownerId,
      created_at: c.createdAt,
    })),
    contacts: data.contacts.map((c) => ({
      id: c.id, company_id: c.companyId, name: c.name, title: c.title, email: c.email, phone: c.phone, owner_id: c.ownerId,
      created_at: c.createdAt,
    })),
    deals: data.deals.map((d) => ({
      id: d.id, title: d.title, pipeline_id: d.pipelineId, stage_id: d.stageId, status: d.status, lost_reason: d.lostReason,
      company_id: d.companyId, owner_id: d.ownerId, value: d.value, currency: d.currency,
      expected_close_date: d.expectedCloseDate, source: d.source, created_at: d.createdAt, updated_at: d.updatedAt,
      closed_at: d.closedAt,
    })),
    deal_contacts: data.deals.flatMap((d) => d.contactIds.map((contact_id, position) => ({ deal_id: d.id, position, contact_id }))),
    stage_visits: data.deals.flatMap((d) =>
      d.stageHistory.map((v, position) => ({
        deal_id: d.id, position, stage_id: v.stageId, entered_at: v.enteredAt, left_at: v.leftAt,
      })),
    ),
    activities: data.activities.map((a) => ({
      id: a.id, type: a.type, subject: a.subject, note: a.note, due_at: a.dueAt, done: a.done ? 1 : 0, done_at: a.doneAt,
      deal_id: a.dealId, contact_id: a.contactId, owner_id: a.ownerId, created_at: a.createdAt,
    })),
  };
}

const str = (v: Row[string]) => v as string;
const opt = (v: Row[string]) => v as string | null;

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

export function fromRows(rows: Rows): CrmData {
  const account = rows.account[0];
  if (!account || rows.pipelines.length === 0) {
    throw new Error(
      "The CRM is empty: its storage holds no account, pipeline or owners yet; set it up with setup_crm.",
    );
  }
  const stages = groupBy(rows.stages, "pipeline_id");
  const contacts = groupBy(rows.deal_contacts, "deal_id");
  const visits = groupBy(rows.stage_visits, "deal_id");
  return {
    version: 1,
    asOf: str(account.as_of),
    account: { name: str(account.name), baseCurrency: account.base_currency as Currency },
    fxRates: Object.fromEntries(rows.fx_rates.map((r) => [str(r.currency), r.rate as number])) as Record<Currency, number>,
    lostReasons: rows.lost_reasons.map((r) => str(r.reason)),
    sources: rows.sources.map((r) => str(r.name)),
    owners: rows.owners.map((o) => ({
      id: str(o.id), name: str(o.name), title: str(o.title), email: str(o.email), kind: o.kind as OwnerKind,
    })),
    pipelines: rows.pipelines.map(
      (p): Pipeline => ({
        id: str(p.id),
        name: str(p.name),
        stages: (stages.get(str(p.id)) ?? []).map(
          (s): Stage => ({
            id: str(s.id),
            name: str(s.name),
            probability: s.probability as number,
            rottenAfterDays: s.rotten_after_days as number | null,
            outcome: s.outcome as Stage["outcome"],
          }),
        ),
      }),
    ),
    companies: rows.companies.map((c) => ({
      id: str(c.id), name: str(c.name), domain: str(c.domain), industry: str(c.industry), size: c.size as CompanySize | null,
      city: str(c.city), ownerId: str(c.owner_id), createdAt: str(c.created_at),
    })),
    contacts: rows.contacts.map((c) => ({
      id: str(c.id), companyId: opt(c.company_id), name: str(c.name), title: str(c.title), email: str(c.email),
      phone: str(c.phone), ownerId: str(c.owner_id), createdAt: str(c.created_at),
    })),
    deals: rows.deals.map((d) => {
      const id = str(d.id);
      return {
        id,
        title: str(d.title),
        pipelineId: str(d.pipeline_id),
        stageId: str(d.stage_id),
        status: d.status as DealStatus,
        lostReason: opt(d.lost_reason),
        companyId: opt(d.company_id),
        contactIds: (contacts.get(id) ?? []).map((c) => str(c.contact_id)),
        ownerId: str(d.owner_id),
        value: d.value as number,
        currency: d.currency as Currency,
        expectedCloseDate: opt(d.expected_close_date),
        source: str(d.source),
        createdAt: str(d.created_at),
        updatedAt: str(d.updated_at),
        closedAt: opt(d.closed_at),
        stageHistory: (visits.get(id) ?? []).map((v) => ({
          stageId: str(v.stage_id), enteredAt: str(v.entered_at), leftAt: opt(v.left_at),
        })),
      };
    }),
    activities: rows.activities.map((a) => ({
      id: str(a.id), type: a.type as ActivityType, subject: str(a.subject), note: str(a.note), dueAt: str(a.due_at),
      done: a.done === 1, doneAt: opt(a.done_at), dealId: opt(a.deal_id), contactId: opt(a.contact_id),
      ownerId: str(a.owner_id), createdAt: str(a.created_at),
    })),
  };
}

/** The demo CRM from `data/crm.json` (generated by `bun run seed`). */
export const seedDemo: Migration = (db: Database) => insertRows(db, TABLES, toRows(demo as unknown as CrmData));
