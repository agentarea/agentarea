import { z } from "zod";
import { ACTIVITY_TYPES, COMPANY_SIZES, CURRENCIES, DEAL_STATUSES, OWNER_KINDS } from "./crm.ts";

const currency = z.enum(CURRENCIES);
const dealStatus = z.enum(DEAL_STATUSES);
const activityType = z.enum(ACTIVITY_TYPES);

export const ownerRefSchema = z.object({ id: z.string(), name: z.string(), handle: z.string(), kind: z.enum(OWNER_KINDS) });
export const ownerSchema = ownerRefSchema.extend({ title: z.string(), email: z.string() });
const ref = z.object({ id: z.string(), name: z.string() });

export const stageSchema = z.object({
  id: z.string(),
  name: z.string(),
  probability: z.number(),
  rottenAfterDays: z.number().nullable(),
  outcome: z.enum(["won", "lost"]).nullable(),
});

export const nextActivitySchema = z.object({
  id: z.string(),
  type: activityType,
  subject: z.string(),
  dueAt: z.string(),
  overdue: z.boolean(),
});

/** One deal as lists, the board and mutations show it. */
export const dealRowSchema = z.object({
  id: z.string(),
  title: z.string(),
  status: dealStatus,
  lostReason: z.string().nullable(),
  pipelineId: z.string(),
  stage: z.object({ id: z.string(), name: z.string(), probability: z.number() }),
  value: z.number(),
  currency,
  /** `value` converted to the account's base currency. */
  baseValue: z.number(),
  company: ref.nullable(),
  contacts: z.array(ref),
  owner: ownerRefSchema,
  expectedCloseDate: z.string().nullable(),
  source: z.string(),
  createdAt: z.string(),
  updatedAt: z.string(),
  closedAt: z.string().nullable(),
  /** Whole days since the deal entered its current stage. */
  daysInStage: z.number(),
  rotting: z.boolean(),
  nextActivity: nextActivitySchema.nullable(),
  overdueActivities: z.number(),
});

const columnSchema = z.object({
  stageId: z.string(),
  count: z.number(),
  total: z.number(),
  weighted: z.number(),
});

/** What `show_pipeline` / `get_pipeline_snapshot` return; money is in `baseCurrency`. */
export const pipelineSnapshotSchema = z.object({
  now: z.string(),
  generatedAt: z.string(),
  account: z.string(),
  baseCurrency: currency,
  fxRates: z.record(z.string(), z.number()),
  pipeline: z.object({ id: z.string(), name: z.string(), stages: z.array(stageSchema) }),
  pipelines: z.array(ref),
  owners: z.array(ownerSchema),
  ownerId: z.string().nullable(),
  kpis: z.object({
    openValue: z.number(),
    openCount: z.number(),
    weightedValue: z.number(),
    wonThisMonth: z.number(),
    wonThisMonthCount: z.number(),
    /** Won share of deals closed in the last 90 days; null when none closed. */
    winRate: z.number().nullable(),
    closedLast90: z.number(),
  }),
  columns: z.array(columnSchema),
  deals: z.array(dealRowSchema),
  lostReasons: z.array(z.string()),
});

export const companyRowSchema = z.object({
  id: z.string(),
  name: z.string(),
  domain: z.string(),
  industry: z.string(),
  size: z.enum(COMPANY_SIZES).nullable(),
  city: z.string(),
  owner: ownerRefSchema,
  openDeals: z.number(),
  contacts: z.number(),
});

export const contactRowSchema = z.object({
  id: z.string(),
  name: z.string(),
  title: z.string(),
  email: z.string(),
  phone: z.string(),
  company: ref.nullable(),
  owner: ownerRefSchema,
});

export const activityRowSchema = z.object({
  id: z.string(),
  type: activityType,
  subject: z.string(),
  note: z.string(),
  dueAt: z.string(),
  done: z.boolean(),
  doneAt: z.string().nullable(),
  overdue: z.boolean(),
  deal: ref.nullable(),
  contact: ref.nullable(),
  owner: ownerRefSchema,
  createdAt: z.string(),
});

/** Everything the deal card shows; `show_deal` returns it. */
export const dealCardSchema = z.object({
  now: z.string(),
  generatedAt: z.string(),
  baseCurrency: currency,
  deal: dealRowSchema,
  stages: z.array(stageSchema),
  stageHistory: z.array(
    z.object({ stageId: z.string(), stageName: z.string(), enteredAt: z.string(), leftAt: z.string().nullable(), days: z.number() }),
  ),
  company: companyRowSchema.nullable(),
  contacts: z.array(contactRowSchema),
  activities: z.array(activityRowSchema),
  lostReasons: z.array(z.string()),
});

export const searchResultSchema = z.object({
  query: z.string().nullable(),
  deals: z.array(dealRowSchema),
  companies: z.array(companyRowSchema),
  contacts: z.array(contactRowSchema),
  /** Matches before `limit` was applied, per kind. */
  totals: z.object({ deals: z.number(), companies: z.number(), contacts: z.number() }),
});

export const dealUpdateSchema = z.object({
  deal: dealRowSchema,
  /** Human-readable list of what changed; empty when the call changed nothing. */
  changes: z.array(z.string()),
});

export type Stage = z.infer<typeof stageSchema>;
export type OwnerRef = z.infer<typeof ownerRefSchema>;
export type DealRow = z.infer<typeof dealRowSchema>;
export type NextActivity = z.infer<typeof nextActivitySchema>;
export type PipelineSnapshot = z.infer<typeof pipelineSnapshotSchema>;
export type Column = z.infer<typeof columnSchema>;
export type CompanyRow = z.infer<typeof companyRowSchema>;
export type ContactRow = z.infer<typeof contactRowSchema>;
export type ActivityRow = z.infer<typeof activityRowSchema>;
export type DealCard = z.infer<typeof dealCardSchema>;
export type SearchResult = z.infer<typeof searchResultSchema>;
export type DealUpdate = z.infer<typeof dealUpdateSchema>;
