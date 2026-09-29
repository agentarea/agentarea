export const DEMO_TIME_ZONE = "UTC";
export const DEMO_NOW_ISO: string = "2026-09-18T09:00:00.000Z";

// Local presentation fixtures, not a backend task or scheduling contract.
export type ConceptTask = {
  id: string;
  goal: string;
  agent: string;
  project: string;
  workstreamId: string;
  status: "running" | "waiting_for_approval" | "scheduled" | "completed";
  needsAttention: boolean;
  scheduledAt: string | null;
  scheduleKind: "one-off" | "recurring-occurrence" | "event-driven";
  source: string;
  activity: string;
  detail: string;
  dependsOn: readonly string[];
  outcome?: { label: string; detail: string };
  decision?: { label: string; description: string };
};

export type ConceptWorkstream = {
  id: string;
  title: string;
  kind: "ongoing" | "one-off";
  brief: string;
  owner: string;
  workingAgreement?: string;
  outcome?: string;
};

export type ConceptViewProps = {
  tasks: readonly ConceptTask[];
  workstreams: readonly ConceptWorkstream[];
  onOpenTask: (id: string, opener: HTMLElement) => void;
};

export const CONCEPT_WORKSTREAMS: readonly ConceptWorkstream[] = [
  {
    id: "seo-operations",
    title: "Manage our SEO",
    kind: "ongoing",
    brief: "Take responsibility for the site's SEO.",
    owner: "SEO Agent",
    workingAgreement:
      "Demo working agreement: run scheduled indexing checks, surface issues, and send proposed site changes for review. This illustrates an agreed routine; it does not authorize changes to any real site.",
  },
  {
    id: "migration-audit",
    title: "Audit SEO before the site migration",
    kind: "one-off",
    brief:
      "Complete a bounded pre-migration audit of indexing and redirect readiness.",
    owner: "SEO Agent",
    outcome: "A reviewed migration audit and prioritized checklist",
  },
];

export const CONCEPT_TASKS: readonly ConceptTask[] = [
  {
    id: "seo-last-check",
    goal: "Review the previous indexing check",
    agent: "SEO Agent",
    project: "Website SEO",
    workstreamId: "seo-operations",
    status: "completed",
    needsAttention: false,
    scheduledAt: null,
    scheduleKind: "event-driven",
    source: "Previous scheduled indexing check",
    activity:
      "The previous indexing check completed and its findings are available.",
    detail:
      "The check captured current indexing evidence and surfaced the pages that need follow-up. This result is recent evidence, not completion of the ongoing SEO responsibility.",
    dependsOn: [],
    outcome: {
      label: "Previous indexing check",
      detail:
        "Indexing evidence is recorded, with affected pages identified for the next review.",
    },
  },
  {
    id: "seo-next-check",
    goal: "Run the next indexing check",
    agent: "SEO Agent",
    project: "Website SEO",
    workstreamId: "seo-operations",
    status: "scheduled",
    needsAttention: false,
    scheduledAt: "2026-09-19T09:00:00.000Z",
    scheduleKind: "recurring-occurrence",
    source: "Scheduled indexing routine",
    activity: "Check the site's current indexing state and surface issues.",
    detail:
      "This is a preview of the next recurring occurrence, not a persisted task. It starts at the scheduled time without implying that the ongoing SEO responsibility has a completion date.",
    dependsOn: [],
  },
  {
    id: "seo-publish-fixes",
    goal: "Publish the reviewed SEO fixes",
    agent: "SEO Agent",
    project: "Website SEO",
    workstreamId: "seo-operations",
    status: "scheduled",
    needsAttention: false,
    scheduledAt: "2026-09-18T15:30:00.000Z",
    scheduleKind: "one-off",
    source: "One-off SEO change schedule",
    activity: "Apply only the fixes accepted through the audit review.",
    detail:
      "This task can proceed only after the demo audit is accepted and the scheduled time arrives. Accepting the audit does not publish site changes immediately.",
    dependsOn: ["audit-review"],
  },
  {
    id: "seo-weekly-review",
    goal: "Review weekly SEO signals",
    agent: "SEO Agent",
    project: "Website SEO",
    workstreamId: "seo-operations",
    status: "scheduled",
    needsAttention: false,
    scheduledAt: "2026-09-21T08:00:00.000Z",
    scheduleKind: "recurring-occurrence",
    source: "Weekly SEO routine",
    activity: "Review indexing signals and surface issues that need attention.",
    detail:
      "This is a projected recurring occurrence, not a persisted task. It represents the next scheduled review within the ongoing responsibility.",
    dependsOn: [],
  },
  {
    id: "seo-recheck-redirects",
    goal: "Recheck migration redirects",
    agent: "SEO Agent",
    project: "Website SEO",
    workstreamId: "seo-operations",
    status: "scheduled",
    needsAttention: false,
    scheduledAt: "2026-09-22T13:00:00.000Z",
    scheduleKind: "one-off",
    source: "One-off redirect recheck schedule",
    activity: "Recheck the redirects covered by the accepted migration audit.",
    detail:
      "This follow-up remains blocked until the demo audit is accepted. Its scheduled start is not a promise of when the ongoing SEO responsibility will be complete.",
    dependsOn: ["audit-review"],
  },
  {
    id: "audit-crawl",
    goal: "Review crawl and indexing evidence",
    agent: "SEO Agent",
    project: "Site Migration",
    workstreamId: "migration-audit",
    status: "completed",
    needsAttention: false,
    scheduledAt: null,
    scheduleKind: "event-driven",
    source: "Pre-migration SEO audit",
    activity: "The crawl and indexing evidence is ready for review.",
    detail:
      "The audit records crawl coverage and indexing evidence needed for the bounded migration review.",
    dependsOn: [],
    outcome: {
      label: "Crawl and indexing evidence",
      detail:
        "Crawl coverage and current indexing findings are recorded in the migration audit.",
    },
  },
  {
    id: "audit-redirects",
    goal: "Check the migration redirects",
    agent: "SEO Agent",
    project: "Site Migration",
    workstreamId: "migration-audit",
    status: "completed",
    needsAttention: false,
    scheduledAt: null,
    scheduleKind: "event-driven",
    source: "Pre-migration SEO audit",
    activity: "The redirect checks are ready for review.",
    detail:
      "The proposed migration redirects were checked after the crawl evidence was assembled, and the findings are included in the audit.",
    dependsOn: ["audit-crawl"],
    outcome: {
      label: "Redirect checks",
      detail:
        "Redirect findings and their priorities are recorded in the migration checklist.",
    },
  },
  {
    id: "audit-review",
    goal: "Accept the migration SEO audit",
    agent: "SEO Agent",
    project: "Site Migration",
    workstreamId: "migration-audit",
    status: "waiting_for_approval",
    needsAttention: true,
    scheduledAt: null,
    scheduleKind: "event-driven",
    source: "Pre-migration review checkpoint",
    activity:
      "The reviewed migration audit and prioritized checklist need your acceptance.",
    detail:
      "Accepting this demo audit records the reviewed audit and checklist as complete. It does not publish site changes or start any scheduled follow-up early.",
    dependsOn: ["audit-crawl", "audit-redirects"],
    decision: {
      label: "Accept demo audit",
      description:
        "Accept the reviewed migration SEO audit and prioritized checklist. This records the audit decision only; it does not authorize or publish changes to a real site.",
    },
  },
];

const TIME_FORMATTER = new Intl.DateTimeFormat("en-GB", {
  hour: "2-digit",
  minute: "2-digit",
  timeZone: DEMO_TIME_ZONE,
});
const DAY_FORMATTER = new Intl.DateTimeFormat("en-GB", {
  weekday: "short",
  day: "numeric",
  month: "short",
  timeZone: DEMO_TIME_ZONE,
});

export function formatConceptTime(iso: string): string {
  return TIME_FORMATTER.format(new Date(iso));
}

export function formatConceptDay(iso: string): string {
  return DAY_FORMATTER.format(new Date(iso));
}

export function isTaskBlocked(
  task: ConceptTask,
  tasks: readonly ConceptTask[]
): boolean {
  return task.dependsOn.some(
    (id) =>
      tasks.find((dependency) => dependency.id === id)?.status !== "completed"
  );
}
