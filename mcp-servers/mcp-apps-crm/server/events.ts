import type { EventType } from "@kit/events/protocol.ts";
import { CURRENCIES, DEAL_STATUSES, OWNER_KINDS, type OwnerKind } from "../shared/crm.ts";

export const DEAL_CREATED = "deal.created";
export const DEAL_STAGE_CHANGED = "deal.stage_changed";
export const DEAL_ASSIGNED = "deal.assigned";
export const CONTACT_CREATED = "contact.created";

type Person = { handle: string; kind: OwnerKind };
type Stage = { id: string; name: string };

/**
 * Checks a subscription's arguments: only `names`, each a non-empty string,
 * handles and stages lowercased without a leading "@", and an argument listed
 * in `choices` one of its values.
 */
function parseArgs(raw: Record<string, unknown>, names: string[], choices: Record<string, readonly string[]> = {}) {
  for (const key of Object.keys(raw)) {
    if (!names.includes(key)) throw new Error(`unknown argument ${JSON.stringify(key)}; use ${names.join(", ")}`);
  }
  const args: Record<string, string | undefined> = {};
  for (const key of names) {
    const value = raw[key];
    if (value === undefined) continue;
    const allowed = choices[key];
    if (allowed) {
      if (!allowed.includes(value as string)) throw new Error(`${key} is ${allowed.join(" or ")}`);
      args[key] = value as string;
      continue;
    }
    if (typeof value !== "string" || !value.trim()) throw new Error(`${key} must be a non-empty string`);
    args[key] = value.trim().replace(/^@/, "").toLowerCase();
  }
  return args;
}

const ownedBy = (owner: string | undefined, kind: OwnerKind | undefined, data: Record<string, unknown>) => {
  const person = data.owner as Person;
  return (owner === undefined || person.handle.toLowerCase() === owner) && (kind === undefined || person.kind === kind);
};

const personSchema = {
  type: "object",
  properties: { handle: { type: "string" }, name: { type: "string" }, kind: { enum: [...OWNER_KINDS] } },
  required: ["handle", "name", "kind"],
};

const refSchema = { type: "object", properties: { id: { type: "string" }, name: { type: "string" } }, required: ["id", "name"] };
const companySchema = { anyOf: [refSchema, { type: "null" }] };

/** The deal as every deal event carries it; `id` and `kind` of an occurrence's data are the event's own. */
const dealProperties = {
  dealId: { type: "string" },
  title: { type: "string" },
  value: { type: "number" },
  currency: { enum: [...CURRENCIES] },
  stage: refSchema,
  status: { enum: [...DEAL_STATUSES] },
  company: companySchema,
  contacts: {
    type: "array",
    items: {
      type: "object",
      properties: { id: { type: "string" }, name: { type: "string" }, email: { type: "string" } },
      required: ["id", "name", "email"],
    },
  },
  owner: personSchema,
  expectedCloseDate: { type: ["string", "null"] },
  source: { type: "string" },
};
const DEAL_REQUIRED = ["dealId", "title", "value", "currency", "stage", "status", "company", "contacts", "owner"];

const ownerArg = { type: "string", description: 'Owner handle, e.g. "scout"' };
const ownerKindArg = { enum: [...OWNER_KINDS], description: "Only owners of this kind" };
const BY = "the caller, or the record's owner when the call carries no caller context";

type OwnerArgs = { owner?: string; ownerKind?: OwnerKind };

const ownerEvent = (raw: Record<string, unknown>): OwnerArgs => {
  const args = parseArgs(raw, ["owner", "ownerKind"], { ownerKind: OWNER_KINDS });
  return { owner: args.owner, ownerKind: args.ownerKind as OwnerKind | undefined };
};

/** Every new deal. */
export const dealCreated: EventType<OwnerArgs> = {
  name: DEAL_CREATED,
  title: "Deal created",
  description: `A new deal was created. Narrow it by owner handle or owner kind. createdBy is ${BY}.`,
  inputSchema: {
    type: "object",
    properties: { owner: ownerArg, ownerKind: ownerKindArg },
    additionalProperties: false,
  },
  payloadSchema: {
    type: "object",
    properties: { ...dealProperties, createdBy: personSchema },
    required: [...DEAL_REQUIRED, "createdBy"],
  },
  parseArguments: ownerEvent,
  admits: (args, data) => ownedBy(args.owner, args.ownerKind, data),
};

type StageArgs = OwnerArgs & { stage?: string };

/** A deal moved stage: forward, back, won, lost or reopened. */
export const dealStageChanged: EventType<StageArgs> = {
  name: DEAL_STAGE_CHANGED,
  title: "Deal stage changed",
  description:
    "A deal moved to another stage, including being won, lost or reopened. Narrow it by the new stage (its id or name; " +
    `"won" or "lost" match the closing stages), owner handle or owner kind. changedBy is ${BY}.`,
  inputSchema: {
    type: "object",
    properties: {
      stage: { type: "string", description: 'The stage the deal moved into: its id or name, or "won" or "lost"' },
      owner: ownerArg,
      ownerKind: ownerKindArg,
    },
    additionalProperties: false,
  },
  payloadSchema: {
    type: "object",
    properties: {
      ...dealProperties,
      from: refSchema,
      to: refSchema,
      outcome: { enum: [...DEAL_STATUSES] },
      lostReason: { type: ["string", "null"] },
      changedBy: personSchema,
    },
    required: [...DEAL_REQUIRED, "from", "to", "outcome", "lostReason", "changedBy"],
  },
  parseArguments(raw) {
    const args = parseArgs(raw, ["stage", "owner", "ownerKind"], { ownerKind: OWNER_KINDS });
    return { stage: args.stage, owner: args.owner, ownerKind: args.ownerKind as OwnerKind | undefined };
  },
  admits(args, data) {
    const to = data.to as Stage;
    const { stage } = args;
    const closes = (stage === "won" || stage === "lost") && data.outcome === stage;
    return (
      (stage === undefined || closes || to.id.toLowerCase() === stage || to.name.toLowerCase() === stage) &&
      ownedBy(args.owner, args.ownerKind, data)
    );
  },
};

/** A deal got an owner, when it was created or later: an agent's trigger subscribes with its own handle. */
export const dealAssigned: EventType<OwnerArgs> = {
  name: DEAL_ASSIGNED,
  title: "Deal assigned",
  description: `A deal got an owner, when it was created or later. Narrow it by owner handle or owner kind. assignedBy is ${BY}.`,
  inputSchema: {
    type: "object",
    properties: { owner: ownerArg, ownerKind: ownerKindArg },
    additionalProperties: false,
  },
  payloadSchema: {
    type: "object",
    properties: { ...dealProperties, assignedBy: personSchema },
    required: [...DEAL_REQUIRED, "assignedBy"],
  },
  parseArguments: ownerEvent,
  admits: (args, data) => ownedBy(args.owner, args.ownerKind, data),
};

type ContactArgs = { owner?: string };

/** Every new contact. */
export const contactCreated: EventType<ContactArgs> = {
  name: CONTACT_CREATED,
  title: "Contact created",
  description: `A new contact was added. Narrow it by owner handle. createdBy is ${BY}.`,
  inputSchema: {
    type: "object",
    properties: { owner: ownerArg },
    additionalProperties: false,
  },
  payloadSchema: {
    type: "object",
    properties: {
      contactId: { type: "string" },
      name: { type: "string" },
      title: { type: "string" },
      email: { type: "string" },
      phone: { type: "string" },
      company: companySchema,
      owner: personSchema,
      createdBy: personSchema,
    },
    required: ["contactId", "name", "company", "owner", "createdBy"],
  },
  parseArguments: (raw) => ({ owner: parseArgs(raw, ["owner"]).owner }),
  admits: (args, data) => ownedBy(args.owner, undefined, data),
};

export const EVENT_TYPES = [dealCreated, dealStageChanged, dealAssigned, contactCreated] as EventType<never>[];
