export const SIGNAL_TYPES = [
  "funding_round",
  "hiring_surge",
  "new_executive",
  "tech_stack_change",
  "website_intent",
  "g2_research",
] as const;
export type SignalType = (typeof SIGNAL_TYPES)[number];

export const SIGNAL_STRENGTHS = ["hot", "warm", "cold"] as const;
export type SignalStrength = (typeof SIGNAL_STRENGTHS)[number];

export const REPLY_CLASSES = [
  "interested",
  "meeting_booked",
  "referral",
  "not_now",
  "objection",
  "out_of_office",
  "unsubscribe",
] as const;
export type ReplyClass = (typeof REPLY_CLASSES)[number];

/** Replies that move a deal forward. Auto-replies never count as a person answering. */
export const REPLY_CLASS_KIND: Record<ReplyClass, "positive" | "neutral" | "negative" | "auto"> = {
  interested: "positive",
  meeting_booked: "positive",
  referral: "positive",
  not_now: "neutral",
  objection: "negative",
  unsubscribe: "negative",
  out_of_office: "auto",
};

export const PERIODS = [7, 30, 90] as const;
export type Period = (typeof PERIODS)[number];

export const FUNNEL_STAGES = [
  "signals",
  "qualified",
  "contacted",
  "opened",
  "replied",
  "positive",
  "meeting",
] as const;
export type FunnelStage = (typeof FUNNEL_STAGES)[number];

export const PERSON_STATUSES = [
  "scheduled",
  "in_sequence",
  "finished",
  "replied",
  "meeting",
  "unsubscribed",
] as const;
export type PersonStatus = (typeof PERSON_STATUSES)[number];

// ---------------------------------------------------------------------------
// Dataset: the file bound to the server through DATA_PATH.
// ---------------------------------------------------------------------------

export type SequenceStepTemplate = {
  step: number;
  /** Days after the first touch. */
  dayOffset: number;
  subject: string;
  body: string;
};

export type Campaign = {
  id: string;
  name: string;
  persona: string;
  description: string;
  sequence: SequenceStepTemplate[];
};

export type Account = {
  id: string;
  name: string;
  domain: string;
  industry: string;
  employees: number;
  region: string;
  hq: string;
};

export type Enrollment = {
  campaignId: string;
  /** The signal that put this person into the sequence. */
  signalId: string | null;
  enrolledAt: string;
};

export type Contact = {
  id: string;
  accountId: string;
  firstName: string;
  lastName: string;
  title: string;
  email: string;
  enrollment: Enrollment | null;
};

export type Signal = {
  id: string;
  accountId: string;
  contactId: string;
  campaignId: string;
  type: SignalType;
  description: string;
  strength: SignalStrength;
  qualified: boolean;
  detectedAt: string;
};

export type Touch = {
  id: string;
  contactId: string;
  campaignId: string;
  step: number;
  subject: string;
  body: string;
  sentAt: string;
  openedAt: string | null;
  clickedAt: string | null;
};

export type Reply = {
  id: string;
  contactId: string;
  campaignId: string;
  touchId: string;
  receivedAt: string;
  body: string;
  classification: ReplyClass;
  handled: boolean;
  handledAt: string | null;
};

export type Meeting = {
  id: string;
  contactId: string;
  accountId: string;
  campaignId: string;
  replyId: string;
  bookedAt: string;
  scheduledFor: string;
  pipelineValue: number;
};

export type OutreachData = {
  version: 1;
  /** Reference "now" of the dataset: period windows end here. */
  asOf: string;
  /** Earliest moment the dataset has activity for. */
  historyStart: string;
  sender: { name: string; title: string; company: string; email: string };
  campaigns: Campaign[];
  accounts: Account[];
  contacts: Contact[];
  signals: Signal[];
  touches: Touch[];
  replies: Reply[];
  meetings: Meeting[];
};
