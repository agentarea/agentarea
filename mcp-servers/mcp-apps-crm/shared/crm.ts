export const DEAL_STATUSES = ["open", "won", "lost"] as const;
export type DealStatus = (typeof DEAL_STATUSES)[number];

export const ACTIVITY_TYPES = ["call", "email", "meeting", "task", "note"] as const;
export type ActivityType = (typeof ACTIVITY_TYPES)[number];

export const CURRENCIES = ["RUB", "USD"] as const;
export type Currency = (typeof CURRENCIES)[number];

export const OWNER_KINDS = ["human", "agent"] as const;
export type OwnerKind = (typeof OWNER_KINDS)[number];

export const COMPANY_SIZES = ["1-10", "11-50", "51-200", "201-500", "501-1000", "1000+"] as const;
export type CompanySize = (typeof COMPANY_SIZES)[number];

// ---------------------------------------------------------------------------
// Dataset: the CRM as the server works with it; stored as tables in the app's sqlite database.
// ---------------------------------------------------------------------------

export type Owner = {
  id: string;
  name: string;
  /** Short unique handle, e.g. "anna"; tools accept it in place of the id. */
  handle: string;
  title: string;
  email: string;
  kind: OwnerKind;
  /** The platform identity this owner is, "user:<id>" or "agent:<id>"; null for someone outside it. */
  platformId: string | null;
};

export type Company = {
  id: string;
  name: string;
  domain: string;
  industry: string;
  size: CompanySize | null;
  city: string;
  ownerId: string;
  createdAt: string;
};

export type Contact = {
  id: string;
  companyId: string | null;
  name: string;
  title: string;
  email: string;
  phone: string;
  ownerId: string;
  createdAt: string;
};

export type Stage = {
  id: string;
  name: string;
  /** Chance a deal in this stage closes as won, 0..1. */
  probability: number;
  /** A deal that sits longer than this in the stage is rotting; null for closed stages. */
  rottenAfterDays: number | null;
  /** Closed stages end the deal: entering one sets the deal's status. */
  outcome: "won" | "lost" | null;
};

export type Pipeline = {
  id: string;
  name: string;
  stages: Stage[];
};

export type StageVisit = {
  stageId: string;
  enteredAt: string;
  leftAt: string | null;
};

export type Deal = {
  id: string;
  title: string;
  pipelineId: string;
  stageId: string;
  status: DealStatus;
  lostReason: string | null;
  companyId: string | null;
  contactIds: string[];
  ownerId: string;
  value: number;
  currency: Currency;
  /** YYYY-MM-DD */
  expectedCloseDate: string | null;
  source: string;
  createdAt: string;
  updatedAt: string;
  closedAt: string | null;
  stageHistory: StageVisit[];
};

export type Activity = {
  id: string;
  type: ActivityType;
  subject: string;
  note: string;
  dueAt: string;
  done: boolean;
  doneAt: string | null;
  dealId: string | null;
  contactId: string | null;
  ownerId: string;
  createdAt: string;
};

export type CrmData = {
  version: 1;
  /** When the dataset was generated. The CRM runs on the real clock from there. */
  asOf: string;
  account: { name: string; baseCurrency: Currency };
  /** Value of one unit of each currency in the base currency. */
  fxRates: Record<Currency, number>;
  lostReasons: string[];
  sources: string[];
  owners: Owner[];
  pipelines: Pipeline[];
  companies: Company[];
  contacts: Contact[];
  deals: Deal[];
  activities: Activity[];
};
