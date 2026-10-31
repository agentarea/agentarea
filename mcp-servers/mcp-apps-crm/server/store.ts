import type { Database } from "bun:sqlite";
import type { Caller } from "@kit/context/caller.ts";
import { appendEvent, type EventData } from "@kit/events/log.ts";
import { insertRows, readRows, syncRows, type Rows } from "@kit/store/rows.ts";
import {
  OWNER_KINDS,
  type Activity,
  type ActivityType,
  type Company,
  type CompanySize,
  type Contact,
  type CrmData,
  type Currency,
  type Deal,
  type DealStatus,
  type Owner,
  type OwnerKind,
  type Stage,
} from "../shared/crm.ts";
import { freeHandle, fromRows, TABLES, toRows } from "./db.ts";
import { CONTACT_CREATED, DEAL_ASSIGNED, DEAL_CREATED, DEAL_STAGE_CHANGED } from "./events.ts";
import { Lookup } from "./lookup.ts";

const DATE = /^\d{4}-\d{2}-\d{2}$/;
const HANDLE = /^[a-z0-9][a-z0-9._-]{0,31}$/;
const PLATFORM_ID = /^(user|agent):[^\s:]+$/;

/** The platform identity a caller is, as owners store it. */
export const platformIdOf = (caller: Caller) => `${caller.kind}:${caller.id}`;

/** An owner as every event names them. */
const personOf = (o: Owner) => ({ handle: o.handle, name: o.name, kind: o.kind });

export type OwnerFields = { name: string; handle?: string; title?: string; email?: string; kind?: OwnerKind; platformId?: string };

export type CrmSetup = {
  account: string;
  baseCurrency: Currency;
  /** Price of one USD in RUB. */
  usdRate: number;
  owners: OwnerFields[];
  /** Names of the open stages, first to last; Won and Lost close the pipeline. */
  stages?: string[];
  sources?: string[];
  lostReasons?: string[];
};

const DEFAULT_STAGES = ["Lead in", "Qualified", "Proposal sent", "Negotiation"];
const DEFAULT_SOURCES = ["Inbound — website", "Outbound", "Referral", "Event", "Partner"];
const DEFAULT_LOST_REASONS = ["Price too high", "Chose a competitor", "No budget", "No decision", "Not a fit"];

export type DealPatch = {
  title?: string;
  value?: number;
  currency?: Currency;
  stageId?: string;
  status?: DealStatus;
  lostReason?: string;
  ownerId?: string;
  companyId?: string | null;
  contactIds?: string[];
  expectedCloseDate?: string | null;
  source?: string;
};

function nextId(ids: Iterable<string>, prefix: string, width: number): string {
  let max = 0;
  for (const id of ids) {
    if (id.startsWith(prefix)) max = Math.max(max, Number.parseInt(id.slice(prefix.length), 10) || 0);
  }
  return `${prefix}${String(max + 1).padStart(width, "0")}`;
}

function checkDate(value: string | null | undefined, field: string) {
  if (value && (!DATE.test(value) || Number.isNaN(Date.parse(value)))) {
    throw new Error(`${field} must be a date like 2026-10-31, got "${value}"`);
  }
}

/** A date-time, or a bare date meaning 09:00 UTC that day. */
function parseMoment(value: string, field: string): number {
  const at = Date.parse(DATE.test(value) ? `${value}T09:00:00Z` : value);
  if (Number.isNaN(at)) throw new Error(`${field} must be an ISO 8601 date or date-time, got "${value}"`);
  return at;
}

/**
 * The CRM as it stands in one store transaction (or read): loaded from the
 * database's rows, changed in memory, and written back by `save`, which
 * touches only the rows that changed.
 */
export class CrmStore {
  readonly #rows: Rows;
  /** Events the changes since `load` produce, appended by `save` in the same transaction. */
  readonly #events: { name: string; data: EventData }[] = [];
  /** Who "me" is for this request: the caller the platform named, when there is one. */
  #me: { owner: Owner } | { unknown: Caller } | null = null;

  private constructor(
    readonly data: CrmData,
    rows: Rows,
  ) {
    this.#rows = rows;
  }

  static load(db: Database): CrmStore {
    const rows = readRows(db, TABLES);
    return new CrmStore(fromRows(rows), rows);
  }

  /** The CRM as stored, or null while its storage holds no account and pipeline yet. */
  static loadIfSetUp(db: Database): CrmStore | null {
    return db.query("SELECT 1 FROM account").get() && db.query("SELECT 1 FROM pipelines").get() ? CrmStore.load(db) : null;
  }

  /** Writes a new CRM into empty storage: the account, its currencies, owners and the sales pipeline. */
  static setup(db: Database, setup: CrmSetup): CrmStore {
    if (db.query("SELECT 1 FROM account").get()) throw new Error("The CRM is already set up; add owners with add_owner.");
    const account = setup.account.trim();
    if (!account) throw new Error("The account needs a name.");
    if (!Number.isFinite(setup.usdRate) || setup.usdRate <= 0) throw new Error("usd_rate is the price of one USD in RUB, a positive number.");
    const names = (setup.stages ?? DEFAULT_STAGES).map((n) => n.trim()).filter(Boolean);
    if (names.length === 0) throw new Error("The pipeline needs at least one open stage.");
    const stages: Stage[] = [
      ...names.map((name, i) => ({
        id: `stage_${i + 1}`,
        name,
        probability: Math.round(((i + 1) / (names.length + 1)) * 100) / 100,
        rottenAfterDays: 14,
        outcome: null,
      })),
      { id: "won", name: "Won", probability: 1, rottenAfterDays: null, outcome: "won" },
      { id: "lost", name: "Lost", probability: 0, rottenAfterDays: null, outcome: "lost" },
    ];
    const data: CrmData = {
      version: 1,
      asOf: new Date().toISOString(),
      account: { name: account, baseCurrency: setup.baseCurrency },
      fxRates: setup.baseCurrency === "RUB" ? { RUB: 1, USD: setup.usdRate } : { RUB: 1 / setup.usdRate, USD: 1 },
      lostReasons: setup.lostReasons ?? DEFAULT_LOST_REASONS,
      sources: setup.sources ?? DEFAULT_SOURCES,
      owners: [],
      pipelines: [{ id: "default", name: "Sales pipeline", stages }],
      companies: [],
      contacts: [],
      deals: [],
      activities: [],
    };
    const store = new CrmStore(data, {});
    if (setup.owners.length === 0) throw new Error("The CRM needs at least one owner.");
    for (const owner of setup.owners) store.addOwner(owner);
    insertRows(db, TABLES, toRows(data));
    return store;
  }

  addOwner(fields: OwnerFields): Owner {
    const name = fields.name.trim();
    if (!name) throw new Error("An owner needs a name.");
    const kind = fields.kind ?? "human";
    if (!OWNER_KINDS.includes(kind)) throw new Error(`An owner is ${OWNER_KINDS.join(" or ")}.`);
    const email = fields.email?.trim() ?? "";
    if (email && this.data.owners.some((o) => o.email.toLowerCase() === email.toLowerCase())) {
      throw new Error(`An owner with ${email} already exists.`);
    }
    const taken = (handle: string) => this.data.owners.some((o) => o.handle === handle);
    const handle = fields.handle?.trim().replace(/^@/, "").toLowerCase() || freeHandle([email.split("@")[0] ?? "", name], taken);
    if (!HANDLE.test(handle)) throw new Error(`"${fields.handle}" is not a handle; use up to 32 latin letters, digits, ".", "_" or "-".`);
    if (handle === "me") throw new Error(`"${handle}" is reserved; pick another handle.`);
    if (taken(handle)) throw new Error(`The handle "${handle}" is taken.`);
    const platformId = fields.platformId === undefined ? null : checkPlatformId(fields.platformId);
    if (platformId && this.data.owners.some((o) => o.platformId === platformId)) throw new Error(`${platformId} is already an owner.`);
    const owner: Owner = {
      id: nextId(this.data.owners.map((o) => o.id), "own_", 2),
      name,
      handle,
      title: fields.title?.trim() ?? "",
      email,
      kind,
      platformId,
    };
    this.data.owners.push(owner);
    return owner;
  }

  /**
   * Makes `caller` "me" for this request. A caller who is no owner yet is added
   * when `join` (a write); a read leaves them unknown, and "me" then refuses.
   */
  identify(caller: Caller, join: boolean): void {
    const platformId = platformIdOf(caller);
    const known = this.data.owners.find((o) => o.platformId === platformId);
    if (known) {
      this.#me = { owner: known };
      return;
    }
    if (!join) {
      this.#me = { unknown: caller };
      return;
    }
    const short = caller.id.slice(0, 8);
    const email = caller.email ?? "";
    const handle = freeHandle([email.split("@")[0] ?? "", `${caller.kind}-${short}`], (h) => this.data.owners.some((o) => o.handle === h));
    const owner = this.addOwner({
      name: caller.email ?? (caller.kind === "agent" ? `Agent ${short}` : `User ${short}`),
      handle,
      // An owner who already has this email is someone else until link_owner says it is the caller.
      email: this.data.owners.some((o) => o.email.toLowerCase() === email.toLowerCase()) ? "" : email,
      kind: caller.kind === "agent" ? "agent" : "human",
      platformId,
    });
    this.#me = { owner };
  }

  /** Ties an owner already in the CRM to their platform identity; an owner linked to someone else stays theirs. */
  linkOwner(ref: string, platformId: string): Owner {
    const owner = this.owner(ref);
    const id = checkPlatformId(platformId);
    if (owner.platformId && owner.platformId !== id) throw new Error(`@${owner.handle} is already ${owner.platformId}.`);
    const other = this.data.owners.find((o) => o.platformId === id);
    if (other && other.id !== owner.id) throw new Error(`${id} is already @${other.handle}.`);
    owner.platformId = id;
    return owner;
  }

  /** The caller, when the platform named one who is an owner. */
  get me(): Owner | null {
    return this.#me && "owner" in this.#me ? this.#me.owner : null;
  }

  /** An owner by id, handle, name or "me". */
  owner(ref: string): Owner {
    const needle = ref.trim().replace(/^@/, "").toLowerCase();
    if (needle === "me") {
      if (this.me) return this.me;
      if (this.#me) throw new Error('"me" is no owner in this CRM yet: make a change first, or ask someone to add you.');
      throw new Error('"me" means nobody when the call carries no caller context; name the owner by id, handle or name.');
    }
    const named = this.data.owners.filter((o) => o.name.toLowerCase() === needle);
    if (named.length > 1 && !this.data.owners.some((o) => o.id === needle || o.handle === needle)) {
      throw new Error(`${named.length} owners are named "${ref}"; name one by handle: ${named.map((o) => `@${o.handle}`).join(", ")}.`);
    }
    const owner =
      this.data.owners.find((o) => o.id === needle) ??
      this.data.owners.find((o) => o.handle === needle) ??
      named[0];
    if (!owner) {
      const known = this.data.owners.map((o) => `${o.handle} (${o.name}${o.kind === "agent" ? ", agent" : ""})`).join(", ");
      throw new Error(`No owner "${ref}". Use an owner id, handle or name: ${known}.`);
    }
    return owner;
  }

  /** Writes what changed since `load` into `db`, inside the caller's transaction. */
  save(db: Database): void {
    syncRows(db, TABLES, this.#rows, toRows(this.data));
    for (const event of this.#events.splice(0)) appendEvent(db, event.name, event.data);
  }

  /** Who made a change: the caller, or the record's owner when the call names no caller. */
  #by(owner: Owner) {
    return personOf(this.me ?? owner);
  }

  #ownerOf(ownerId: string): Owner {
    return this.data.owners.find((o) => o.id === ownerId)!;
  }

  #company(companyId: string | null) {
    const company = companyId ? this.data.companies.find((c) => c.id === companyId) : undefined;
    return company ? { id: company.id, name: company.name } : null;
  }

  /** The deal as its events carry it. */
  #dealData(deal: Deal) {
    const stage = this.data.pipelines.find((p) => p.id === deal.pipelineId)!.stages.find((s) => s.id === deal.stageId)!;
    return {
      dealId: deal.id,
      title: deal.title,
      value: deal.value,
      currency: deal.currency,
      stage: { id: stage.id, name: stage.name },
      status: deal.status,
      company: this.#company(deal.companyId),
      contacts: deal.contactIds.map((id) => {
        const contact = this.data.contacts.find((c) => c.id === id)!;
        return { id: contact.id, name: contact.name, email: contact.email };
      }),
      owner: personOf(this.#ownerOf(deal.ownerId)),
      expectedCloseDate: deal.expectedCloseDate,
      source: deal.source,
    };
  }

  #assigned(deal: Deal): void {
    this.#events.push({ name: DEAL_ASSIGNED, data: { ...this.#dealData(deal), assignedBy: this.#by(this.#ownerOf(deal.ownerId)) } });
  }

  /** The CRM runs on the real clock, never earlier than the moment the dataset was generated. */
  now(): string {
    return new Date(Math.max(Date.now(), Date.parse(this.data.asOf))).toISOString();
  }

  createCompany(input: {
    name: string;
    ownerId: string;
    domain?: string;
    industry?: string;
    size?: CompanySize;
    city?: string;
  }): Company {
    const lookup = new Lookup(this.data);
    const owner = this.owner(input.ownerId);
    const name = input.name.trim();
    if (!name) throw new Error("name must not be empty");
    const existing = this.data.companies.find((c) => c.name.toLowerCase() === name.toLowerCase());
    if (existing) throw new Error(`Company “${existing.name}” already exists as ${existing.id}`);
    const company: Company = {
      id: nextId(lookup.companies.keys(), "cmp_", 3),
      name,
      domain: input.domain?.trim() ?? "",
      industry: input.industry?.trim() ?? "",
      size: input.size ?? null,
      city: input.city?.trim() ?? "",
      ownerId: owner.id,
      createdAt: this.now(),
    };
    this.data.companies.push(company);
    return company;
  }

  createContact(input: {
    name: string;
    companyId?: string;
    ownerId?: string;
    title?: string;
    email?: string;
    phone?: string;
  }): Contact {
    const lookup = new Lookup(this.data);
    const company = input.companyId ? lookup.requireCompany(input.companyId) : null;
    const ownerId = input.ownerId ? this.owner(input.ownerId).id : (company?.ownerId ?? this.me?.id);
    if (!ownerId) throw new Error("owner_id is required when the contact has no company to inherit an owner from");
    const name = input.name.trim();
    if (!name) throw new Error("name must not be empty");
    const email = input.email?.trim() ?? "";
    const existing = email && this.data.contacts.find((c) => c.email.toLowerCase() === email.toLowerCase());
    if (existing) throw new Error(`A contact with email ${email} already exists: ${existing.id} (${existing.name})`);
    const contact: Contact = {
      id: nextId(lookup.contacts.keys(), "ct_", 3),
      companyId: company?.id ?? null,
      name,
      title: input.title?.trim() ?? "",
      email,
      phone: input.phone?.trim() ?? "",
      ownerId,
      createdAt: this.now(),
    };
    this.data.contacts.push(contact);
    const owner = this.#ownerOf(ownerId);
    this.#events.push({
      name: CONTACT_CREATED,
      data: {
        contactId: contact.id,
        name: contact.name,
        title: contact.title,
        email: contact.email,
        phone: contact.phone,
        company: this.#company(contact.companyId),
        owner: personOf(owner),
        createdBy: this.#by(owner),
      },
    });
    return contact;
  }

  createDeal(input: {
    title: string;
    value: number;
    currency?: Currency;
    companyId?: string;
    contactIds?: string[];
    ownerId?: string;
    pipelineId?: string;
    stageId?: string;
    expectedCloseDate?: string;
    source?: string;
  }): Deal {
    const lookup = new Lookup(this.data);
    const company = input.companyId ? lookup.requireCompany(input.companyId) : null;
    const contactIds = [...new Set(input.contactIds ?? [])];
    for (const id of contactIds) lookup.requireContact(id);
    const ownerId = input.ownerId ? this.owner(input.ownerId).id : (company?.ownerId ?? this.me?.id);
    if (!ownerId) throw new Error("owner_id is required when the deal has no company to inherit an owner from");
    const pipeline = lookup.requirePipeline(input.pipelineId ?? this.data.pipelines[0].id);
    const stage = input.stageId
      ? lookup.requireStage(pipeline, input.stageId)
      : pipeline.stages.find((s) => s.outcome === null)!;
    if (stage.outcome) {
      throw new Error(`A deal starts in an open stage; create it, then close it with update_deal (status "${stage.outcome}")`);
    }
    checkDate(input.expectedCloseDate, "expected_close_date");
    const title = input.title.trim();
    if (!title) throw new Error("title must not be empty");
    const now = this.now();
    const deal: Deal = {
      id: nextId(lookup.deals.keys(), "deal_", 3),
      title,
      pipelineId: pipeline.id,
      stageId: stage.id,
      status: "open",
      lostReason: null,
      companyId: company?.id ?? null,
      contactIds,
      ownerId,
      value: input.value,
      currency: input.currency ?? this.data.account.baseCurrency,
      expectedCloseDate: input.expectedCloseDate ?? null,
      source: input.source?.trim() || "Manual entry",
      createdAt: now,
      updatedAt: now,
      closedAt: null,
      stageHistory: [{ stageId: stage.id, enteredAt: now, leftAt: null }],
    };
    this.data.deals.push(deal);
    this.#events.push({ name: DEAL_CREATED, data: { ...this.#dealData(deal), createdBy: this.#by(this.#ownerOf(ownerId)) } });
    this.#assigned(deal);
    return deal;
  }

  /** Applies a patch; returns what changed in words. A stage move records the stage history. */
  updateDeal(dealId: string, patch: DealPatch): { deal: Deal; changes: string[] } {
    const lookup = new Lookup(this.data);
    const deal = lookup.requireDeal(dealId);
    const pipeline = lookup.requirePipeline(deal.pipelineId);
    const current = lookup.stageOf(deal);
    const closedStage = (outcome: "won" | "lost") => {
      const stage = pipeline.stages.find((s) => s.outcome === outcome);
      if (!stage) throw new Error(`Pipeline "${pipeline.id}" has no ${outcome} stage`);
      return stage;
    };
    const lastOpenStage = () => {
      const visit = deal.stageHistory.findLast((v) => pipeline.stages.find((s) => s.id === v.stageId)?.outcome === null);
      return visit ? lookup.requireStage(pipeline, visit.stageId) : pipeline.stages.find((s) => s.outcome === null)!;
    };

    let target: Stage = current;
    const requested = patch.stageId === undefined ? null : lookup.requireStage(pipeline, patch.stageId);
    if (patch.status === "won" || patch.status === "lost") {
      target = closedStage(patch.status);
      if (requested && requested.id !== target.id) {
        throw new Error(`stage_id "${requested.id}" contradicts status "${patch.status}"; pass one of them`);
      }
    } else if (patch.status === "open") {
      if (requested?.outcome) throw new Error(`stage_id "${requested.id}" closes the deal; it contradicts status "open"`);
      target = requested ?? (current.outcome ? lastOpenStage() : current);
    } else if (requested) {
      target = requested;
    }

    const changes: string[] = [];
    const now = this.now();
    const reason = patch.lostReason?.trim();
    if (patch.lostReason !== undefined && target.outcome !== "lost") {
      throw new Error("lost_reason applies only to a lost deal; pass status \"lost\" with it");
    }
    if (target.outcome === "lost" && !reason && !(current.outcome === "lost" && deal.lostReason)) {
      throw new Error("Marking a deal lost needs a lost_reason, e.g. one of: " + this.data.lostReasons.join("; "));
    }

    // Validate everything before touching the deal, so a rejected call changes nothing.
    const owner = patch.ownerId === undefined ? null : this.owner(patch.ownerId);
    const company = patch.companyId ? lookup.requireCompany(patch.companyId) : null;
    const contactIds = patch.contactIds === undefined ? null : [...new Set(patch.contactIds)];
    for (const id of contactIds ?? []) lookup.requireContact(id);
    checkDate(patch.expectedCloseDate, "expected_close_date");
    if (patch.title !== undefined && !patch.title.trim()) throw new Error("title must not be empty");

    const moved = target.id !== current.id;
    if (moved) {
      const visit = deal.stageHistory.at(-1);
      if (visit && visit.leftAt === null) visit.leftAt = now;
      deal.stageHistory.push({ stageId: target.id, enteredAt: now, leftAt: null });
      deal.stageId = target.id;
      deal.status = target.outcome ?? "open";
      deal.closedAt = target.outcome ? now : null;
      deal.lostReason = target.outcome === "lost" ? reason! : null;
      changes.push(
        target.outcome === "won"
          ? `marked won (from ${current.name})`
          : target.outcome === "lost"
            ? `marked lost: ${reason}`
            : current.outcome
              ? `reopened in ${target.name}`
              : `stage ${current.name} → ${target.name}`,
      );
    } else if (target.outcome === "lost" && reason && reason !== deal.lostReason) {
      deal.lostReason = reason;
      changes.push(`lost reason → ${reason}`);
    }

    if (patch.title !== undefined && patch.title.trim() !== deal.title) {
      deal.title = patch.title.trim();
      changes.push(`title → ${deal.title}`);
    }
    if (patch.value !== undefined && patch.value !== deal.value) {
      changes.push(`value ${deal.value} → ${patch.value}`);
      deal.value = patch.value;
    }
    if (patch.currency !== undefined && patch.currency !== deal.currency) {
      changes.push(`currency ${deal.currency} → ${patch.currency}`);
      deal.currency = patch.currency;
    }
    const reassigned = owner !== null && owner.id !== deal.ownerId;
    if (reassigned) {
      deal.ownerId = owner.id;
      changes.push(`owner → ${owner.name}`);
    }
    if (patch.companyId !== undefined && patch.companyId !== deal.companyId) {
      deal.companyId = company?.id ?? null;
      changes.push(company ? `company → ${company.name}` : "company removed");
    }
    if (contactIds && contactIds.join() !== deal.contactIds.join()) {
      deal.contactIds = contactIds;
      changes.push(`contacts → ${contactIds.map((id) => lookup.contacts.get(id)!.name).join(", ") || "none"}`);
    }
    if (patch.expectedCloseDate !== undefined && patch.expectedCloseDate !== deal.expectedCloseDate) {
      deal.expectedCloseDate = patch.expectedCloseDate;
      changes.push(`expected close → ${patch.expectedCloseDate ?? "none"}`);
    }
    if (patch.source !== undefined && patch.source.trim() !== deal.source) {
      deal.source = patch.source.trim();
      changes.push(`source → ${deal.source}`);
    }
    if (changes.length > 0) deal.updatedAt = now;
    if (moved) {
      this.#events.push({
        name: DEAL_STAGE_CHANGED,
        data: {
          ...this.#dealData(deal),
          from: { id: current.id, name: current.name },
          to: { id: target.id, name: target.name },
          outcome: deal.status,
          lostReason: deal.lostReason,
          changedBy: this.#by(this.#ownerOf(deal.ownerId)),
        },
      });
    }
    if (reassigned) this.#assigned(deal);
    return { deal, changes };
  }

  logActivity(input: {
    type: ActivityType;
    subject: string;
    dealId?: string;
    contactId?: string;
    ownerId?: string;
    dueAt?: string;
    done?: boolean;
    note?: string;
  }): Activity {
    const lookup = new Lookup(this.data);
    if (!input.dealId && !input.contactId) throw new Error("An activity needs a deal_id, a contact_id, or both");
    const deal = input.dealId ? lookup.requireDeal(input.dealId) : null;
    const contact = input.contactId ? lookup.requireContact(input.contactId) : null;
    const ownerId = input.ownerId ? this.owner(input.ownerId).id : (deal?.ownerId ?? contact!.ownerId);
    const subject = input.subject.trim();
    if (!subject) throw new Error("subject must not be empty");
    const now = this.now();
    const due = input.dueAt === undefined ? Date.parse(now) : parseMoment(input.dueAt, "due_at");
    const done = input.done ?? due <= Date.parse(now);
    const activity: Activity = {
      id: nextId(lookup.activities.keys(), "act_", 4),
      type: input.type,
      subject,
      note: input.note?.trim() ?? "",
      dueAt: new Date(due).toISOString(),
      done,
      doneAt: done ? new Date(Math.min(due, Date.parse(now))).toISOString() : null,
      dealId: deal?.id ?? null,
      contactId: contact?.id ?? null,
      ownerId,
      createdAt: now,
    };
    this.data.activities.push(activity);
    if (deal) deal.updatedAt = now;
    return activity;
  }

  completeActivity(activityId: string, done: boolean): { activity: Activity; changed: boolean } {
    const lookup = new Lookup(this.data);
    const activity = lookup.requireActivity(activityId);
    if (activity.done === done) return { activity, changed: false };
    const now = this.now();
    activity.done = done;
    activity.doneAt = done ? now : null;
    const deal = activity.dealId ? lookup.deals.get(activity.dealId) : undefined;
    if (deal) deal.updatedAt = now;
    return { activity, changed: true };
  }
}

function checkPlatformId(value: string): string {
  const id = value.trim();
  if (!PLATFORM_ID.test(id)) throw new Error(`"${value}" is not a platform identity; use "user:<id>" or "agent:<id>".`);
  return id;
}
