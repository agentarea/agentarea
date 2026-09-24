import { z } from "zod";
import {
  FUNNEL_STAGES,
  PERSON_STATUSES,
  REPLY_CLASSES,
  SIGNAL_STRENGTHS,
  SIGNAL_TYPES,
  type ReplyClass,
} from "./outreach.ts";

// ---------------------------------------------------------------------------
// Snapshot: what `get_outreach_snapshot` returns to the view.
// ---------------------------------------------------------------------------

const signalType = z.enum(SIGNAL_TYPES);
const signalStrength = z.enum(SIGNAL_STRENGTHS);
const replyClass = z.enum(REPLY_CLASSES);

export const kpiSchema = z.object({
  key: z.enum(["signals", "contacted", "reply_rate", "positive", "meetings", "pipeline"]),
  label: z.string(),
  format: z.enum(["number", "percent", "currency"]),
  value: z.number(),
  /** Same metric over the previous period; null when the data does not cover it. */
  previous: z.number().nullable(),
});

export const funnelStageSchema = z.object({
  key: z.enum(FUNNEL_STAGES),
  label: z.string(),
  count: z.number(),
  /** Share of the previous stage that reached this one; null for the first stage. */
  conversion: z.number().nullable(),
});

const signalRefSchema = z.object({
  type: signalType,
  description: z.string(),
  strength: signalStrength,
  detectedAt: z.string(),
});

export const signalRowSchema = signalRefSchema.extend({
  id: z.string(),
  qualified: z.boolean(),
  status: z.enum(["not_contacted", "in_sequence"]),
  campaign: z.object({ id: z.string(), name: z.string() }),
  account: z.object({
    name: z.string(),
    domain: z.string(),
    industry: z.string(),
    employees: z.number(),
    region: z.string(),
  }),
  contact: z.object({ id: z.string(), name: z.string(), title: z.string() }),
});

export const threadMessageSchema = z.object({
  direction: z.enum(["outbound", "inbound"]),
  step: z.number().nullable(),
  from: z.string(),
  subject: z.string(),
  body: z.string(),
  at: z.string(),
  openedAt: z.string().nullable(),
  clickedAt: z.string().nullable(),
});

export const replyRowSchema = z.object({
  id: z.string(),
  receivedAt: z.string(),
  classification: replyClass,
  handled: z.boolean(),
  body: z.string(),
  contact: z.object({ id: z.string(), name: z.string(), title: z.string(), email: z.string() }),
  account: z.object({ name: z.string(), domain: z.string(), industry: z.string() }),
  campaign: z.object({ id: z.string(), name: z.string() }),
  signal: signalRefSchema.nullable(),
  thread: z.array(threadMessageSchema),
  suggestedNextStep: z.string(),
  meeting: z.object({ scheduledFor: z.string(), pipelineValue: z.number() }).nullable(),
});

const campaignRefSchema = z.object({ id: z.string(), name: z.string() });

export const sequenceStateSchema = z.object({
  step: z.number(),
  totalSteps: z.number(),
  lastTouchAt: z.string().nullable(),
  nextTouchAt: z.string().nullable(),
  status: z.enum(PERSON_STATUSES),
});

export const personRowSchema = sequenceStateSchema.extend({
  contactId: z.string(),
  name: z.string(),
  title: z.string(),
  company: z.string(),
  domain: z.string(),
  campaign: campaignRefSchema,
  signal: signalRefSchema.nullable(),
  replyClass: replyClass.nullable(),
  /** Furthest funnel stage this person reached. */
  stage: z.enum(FUNNEL_STAGES),
});

export const LEAD_STEP_STATES = ["replied", "clicked", "opened", "sent", "scheduled", "skipped", "not_started"] as const;

/** Everything the lead card shows about one person; `show_lead_card` returns it. */
export const leadCardSchema = z.object({
  asOf: z.string(),
  generatedAt: z.string(),
  contact: z.object({ id: z.string(), name: z.string(), firstName: z.string(), title: z.string(), email: z.string() }),
  account: z.object({
    name: z.string(),
    domain: z.string(),
    industry: z.string(),
    employees: z.number(),
    region: z.string(),
    hq: z.string(),
  }),
  /** The signal that enrolled this person, or the newest one on them if they are not enrolled. */
  signal: signalRefSchema.extend({ id: z.string() }).nullable(),
  /** Other recent signals on the same account. */
  accountSignals: z.array(signalRefSchema.extend({ id: z.string() })),
  enrollment: sequenceStateSchema.extend({ campaign: campaignRefSchema, enrolledAt: z.string() }).nullable(),
  /** Campaign `add_to_sequence` would use for someone not enrolled yet. */
  targetCampaign: campaignRefSchema.nullable(),
  steps: z.array(
    z.object({
      step: z.number(),
      subject: z.string(),
      state: z.enum(LEAD_STEP_STATES),
      sentAt: z.string().nullable(),
      openedAt: z.string().nullable(),
      clickedAt: z.string().nullable(),
      /** When a step not sent yet is due. */
      dueAt: z.string().nullable(),
    }),
  ),
  thread: z.array(threadMessageSchema),
  reply: z
    .object({ id: z.string(), classification: replyClass, handled: z.boolean(), receivedAt: z.string() })
    .nullable(),
  meeting: z.object({ scheduledFor: z.string(), pipelineValue: z.number() }).nullable(),
  suggestedNextStep: z.string(),
});

export const seriesPointSchema = z.object({
  date: z.string(),
  ...Object.fromEntries(REPLY_CLASSES.map((c) => [c, z.number()])),
} as { date: z.ZodString } & Record<ReplyClass, z.ZodNumber>);

export const snapshotSchema = z.object({
  asOf: z.string(),
  generatedAt: z.string(),
  period: z.union([z.literal(7), z.literal(30), z.literal(90)]),
  campaign: z.string().nullable(),
  campaigns: z.array(z.object({ id: z.string(), name: z.string(), persona: z.string() })),
  sender: z.object({ name: z.string(), company: z.string() }),
  kpis: z.array(kpiSchema),
  funnel: z.array(funnelStageSchema),
  signals: z.array(signalRowSchema),
  replies: z.array(replyRowSchema),
  people: z.array(personRowSchema),
  series: z.array(seriesPointSchema),
});

export type Kpi = z.infer<typeof kpiSchema>;
export type FunnelStageRow = z.infer<typeof funnelStageSchema>;
export type SignalRow = z.infer<typeof signalRowSchema>;
export type ReplyRow = z.infer<typeof replyRowSchema>;
export type ThreadMessage = z.infer<typeof threadMessageSchema>;
export type SignalRef = z.infer<typeof signalRefSchema>;
export type SequenceState = z.infer<typeof sequenceStateSchema>;
export type PersonRow = z.infer<typeof personRowSchema>;
export type LeadCard = z.infer<typeof leadCardSchema>;
export type LeadStep = LeadCard["steps"][number];
export type SeriesPoint = z.infer<typeof seriesPointSchema>;
export type Snapshot = z.infer<typeof snapshotSchema>;

export const enrolledContactSchema = z.object({
  id: z.string(),
  name: z.string(),
  company: z.string(),
  campaign: z.object({ id: z.string(), name: z.string() }),
  status: z.literal("scheduled"),
  step: z.literal(1),
  enrolledAt: z.string(),
});
export type EnrolledContact = z.infer<typeof enrolledContactSchema>;

export const handledReplySchema = z.object({
  id: z.string(),
  handled: z.literal(true),
  handledAt: z.string(),
});
export type HandledReply = z.infer<typeof handledReplySchema>;
