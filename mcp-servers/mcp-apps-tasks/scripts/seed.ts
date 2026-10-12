/**
 * Generates `data/tasks.json`: a deterministic issue tracker dataset.
 *
 * Every random choice comes from one PRNG with a fixed seed and every date is
 * relative to a fixed `AS_OF`, so running the script twice yields the same file.
 */
import fs from "node:fs/promises";
import path from "node:path";
import {
  PRIORITIES,
  type Activity,
  type Comment,
  type Issue,
  type Label,
  type Person,
  type Priority,
  type Project,
  type Status,
  type TasksData,
} from "../shared/tasks.ts";

const SEED = 0x7a5c_2026;
const AS_OF = Date.parse("2026-10-05T09:00:00.000Z");
const HOUR = 3_600_000;
const DAY = 24 * HOUR;
const OUT = path.join(import.meta.dirname, "..", "data", "tasks.json");

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
const pad = (n: number, width = 3) => String(n).padStart(width, "0");
const iso = (ms: number) => new Date(ms).toISOString();
const day = (ms: number) => iso(ms).slice(0, 10);

/** Moves a timestamp into weekday working hours (08:00–18:00 UTC). */
function workingHours(ms: number): number {
  const date = new Date(ms);
  const hour = date.getUTCHours();
  if (hour < 8) date.setUTCHours(8 + int(0, 2), int(0, 59));
  if (hour >= 18) {
    date.setUTCDate(date.getUTCDate() + 1);
    date.setUTCHours(8 + int(0, 3), int(0, 59));
  }
  const weekday = date.getUTCDay();
  if (weekday === 6) date.setUTCDate(date.getUTCDate() + 2);
  if (weekday === 0) date.setUTCDate(date.getUTCDate() + 1);
  return date.getTime();
}

// ---------------------------------------------------------------------------
// People, projects, labels
// ---------------------------------------------------------------------------

const PEOPLE: Person[] = [
  { id: "usr_01", name: "Maya Chen", handle: "maya", kind: "human", title: "Engineering Manager" },
  { id: "usr_02", name: "Daniel Okafor", handle: "daniel", kind: "human", title: "Senior Frontend Engineer" },
  { id: "usr_03", name: "Priya Raman", handle: "priya", kind: "human", title: "Platform Engineer" },
  { id: "usr_04", name: "Lena Fischer", handle: "lena", kind: "human", title: "Growth Marketing Lead" },
  { id: "agt_01", name: "Atlas", handle: "atlas", kind: "agent", title: "Triage and QA agent" },
  { id: "agt_02", name: "Relay", handle: "relay", kind: "agent", title: "Release and operations agent" },
];
const VIEWER = "usr_01";
const AGENTS = PEOPLE.filter((p) => p.kind === "agent").map((p) => p.id);

const LABELS: Label[] = [
  { name: "bug", color: "red" },
  { name: "customer", color: "orange" },
  { name: "feature", color: "blue" },
  { name: "improvement", color: "teal" },
  { name: "tech-debt", color: "gray" },
  { name: "design", color: "pink" },
  { name: "performance", color: "yellow" },
  { name: "accessibility", color: "purple" },
  { name: "docs", color: "gray" },
  { name: "infra", color: "green" },
  { name: "security", color: "red" },
  { name: "launch", color: "purple" },
  { name: "content", color: "blue" },
  { name: "seo", color: "green" },
  { name: "website", color: "teal" },
  { name: "event", color: "orange" },
  { name: "analytics", color: "yellow" },
  { name: "partnerships", color: "pink" },
];

type Template = { title: string; labels: string[]; note: string; children?: Omit<Template, "children">[] };
type ProjectSeed = Omit<Project, "nextNumber"> & {
  /** Who works this project's issues, with relative weights. */
  team: Record<string, number>;
  voice: Voice;
  estimates: number;
  templates: Template[];
};

const PROJECTS: ProjectSeed[] = [
  {
    id: "prj_web",
    key: "WEB",
    name: "Web App",
    description: "The customer-facing web application: UI, client performance and the APIs it talks to.",
    leadId: "usr_02",
    team: { usr_02: 5, usr_01: 2, agt_01: 3, usr_03: 1 },
    voice: "eng",
    estimates: 0.8,
    templates: [
      {
        title: "Redesign the onboarding checklist",
        labels: ["feature", "design"],
        note: "New workspaces drop off before inviting a teammate. The checklist should lead with the two steps that predict retention.",
        children: [
          { title: "Checklist progress API endpoint", labels: ["feature"], note: "Return per-step completion for the current workspace so the client stops recomputing it." },
          { title: "Empty states for new workspaces", labels: ["design"], note: "Boards, inbox and reports all render blank for a brand-new workspace." },
          { title: "Track checklist completion events", labels: ["analytics"], note: "We need step-level events to see where people stall." },
        ],
      },
      {
        title: "Dark mode polish pass",
        labels: ["improvement", "design"],
        note: "A sweep over the screens that still hardcode light colors.",
        children: [
          { title: "Fix low-contrast chart tooltips in dark mode", labels: ["bug", "accessibility"], note: "Tooltip text sits at roughly 2:1 contrast on the dark card background." },
          { title: "Theme-aware code block highlighting", labels: ["improvement"], note: "Code blocks keep the light syntax theme after switching to dark." },
        ],
      },
      { title: "Login loop when the session token expires mid-request", labels: ["bug", "customer"], note: "Two enterprise customers report being bounced between /login and /home after lunch breaks. Looks like a refresh race." },
      { title: "Search results ignore the workspace filter", labels: ["bug"], note: "Global search returns issues from every workspace the user belongs to, regardless of the selected one." },
      { title: "Keyboard shortcuts for issue navigation", labels: ["feature"], note: "J/K to move, Enter to open, Esc to close. Power users keep asking for it." },
      { title: "Migrate settings pages to the new form components", labels: ["tech-debt"], note: "Settings still use the legacy form wrapper, which blocks removing it from the bundle." },
      { title: "Virtualize the export preview table", labels: ["performance"], note: "Previewing a 10k-row export freezes the tab for several seconds." },
      { title: "File upload fails silently over 25 MB", labels: ["bug", "customer"], note: "The request is rejected by the proxy and the UI shows a finished upload anyway." },
      { title: "Inline editing for project names", labels: ["feature"], note: "Renaming a project takes four clicks through settings today." },
      { title: "Adopt the React compiler on the editor route", labels: ["tech-debt", "performance"], note: "Profiling shows most editor re-renders come from unstable callbacks." },
      { title: "Notification preferences page", labels: ["feature"], note: "Let people choose email, in-app or none per event type." },
      { title: "Avatar fallback broken in Safari 18", labels: ["bug"], note: "Initials render offset by a few pixels and clip on Retina displays." },
      { title: "Cut the editor route bundle below 300 KB", labels: ["performance"], note: "The editor chunk grew to 540 KB gzipped after the diagram plugin landed." },
      { title: "Focus order in the command palette", labels: ["accessibility", "improvement"], note: "Tab jumps from the input to the page behind the palette." },
      { title: "Billing page shows the old plan after upgrading", labels: ["bug", "customer"], note: "The plan card reads from a cached subscription until a hard reload." },
      { title: "Document the component library in Storybook", labels: ["docs"], note: "New contributors rebuild components that already exist because nothing is discoverable." },
    ],
  },
  {
    id: "prj_ops",
    key: "OPS",
    name: "Platform & Ops",
    description: "Infrastructure, reliability, security and the on-call rotation.",
    leadId: "usr_03",
    team: { usr_03: 5, agt_02: 4, usr_01: 1 },
    voice: "eng",
    estimates: 0.75,
    templates: [
      {
        title: "Postgres 17 upgrade",
        labels: ["infra"],
        note: "Primary and replicas move from 15 to 17 with under five minutes of write downtime.",
        children: [
          { title: "Rehearse the upgrade on a staging snapshot", labels: ["infra"], note: "Restore last night's snapshot and time a full pg_upgrade run." },
          { title: "Update pgbouncer and connection limits", labels: ["infra"], note: "The new version changes the default max_connections we rely on." },
          { title: "Write the rollback runbook", labels: ["docs"], note: "Step-by-step rollback, including how to repoint the replicas." },
        ],
      },
      {
        title: "SOC 2 evidence collection",
        labels: ["security"],
        note: "Evidence for the Type II window that closes at the end of the quarter.",
        children: [
          { title: "Export quarterly access reviews", labels: ["security"], note: "Auditors want signed-off access reviews for every production system." },
          { title: "Enable audit logging on the admin API", labels: ["security"], note: "Every admin action needs actor, target and timestamp retained for a year." },
        ],
      },
      { title: "Certificate renewal failed for the status page", labels: ["bug", "infra"], note: "The ACME challenge fails since the DNS move; the current certificate expires in nine days." },
      { title: "Nightly backup job overruns its window", labels: ["infra", "performance"], note: "The 02:00 backup now runs past 06:00 and overlaps with the EU morning peak." },
      { title: "Rotate the leaked CI deploy token", labels: ["security"], note: "A deploy token was printed in a public build log. Rotate it and scrub the log." },
      { title: "Autoscale workers on queue depth", labels: ["infra", "feature"], note: "Scale on pending jobs instead of CPU, which lags the real backlog by minutes." },
      { title: "Deduplicate disk pressure alerts", labels: ["improvement"], note: "One full disk pages on-call eleven times. Group by volume and back off." },
      { title: "Move container builds to the shared runner pool", labels: ["infra", "tech-debt"], note: "Dedicated build VMs sit idle most of the day." },
      { title: "Pin base images and turn on vulnerability scanning", labels: ["security"], note: "Images float on :latest and nobody sees CVEs until a customer asks." },
      { title: "API latency dashboard by route", labels: ["feature"], note: "p50/p95/p99 per route with deploy markers." },
      { title: "Clean up orphaned volumes in the EU cluster", labels: ["tech-debt"], note: "Roughly 40 unattached volumes are still billed every month." },
      { title: "Rate limiting for the public webhook endpoint", labels: ["security", "feature"], note: "A misconfigured integration sent 2M requests in an hour last week." },
      { title: "Terraform state drift in the networking module", labels: ["bug", "infra"], note: "Plan shows security group changes nobody made in code." },
      { title: "Refresh the on-call handbook", labels: ["docs"], note: "Half the runbook links point at dashboards that no longer exist." },
      { title: "Tag every cloud resource by team", labels: ["improvement"], note: "Finance needs a cost split by team before budget planning." },
      { title: "502s from the edge proxy right after deploys", labels: ["bug"], note: "Each deploy produces a burst of 502s for about 20 seconds. Probably missing connection draining." },
    ],
  },
  {
    id: "prj_mkt",
    key: "MKT",
    name: "Marketing",
    description: "Launches, website, content and campaigns.",
    leadId: "usr_04",
    team: { usr_04: 6, agt_01: 2, usr_01: 1, usr_02: 1 },
    voice: "mkt",
    estimates: 0.4,
    templates: [
      {
        title: "Q4 launch: Workflows",
        labels: ["launch"],
        note: "Coordinated launch of Workflows across blog, site, email and Product Hunt.",
        children: [
          { title: "Launch blog post", labels: ["content"], note: "Story-first post with two customer quotes and a short demo GIF." },
          { title: "Product Hunt launch kit", labels: ["launch"], note: "Gallery images, maker comment, and a list of supporters to notify." },
          { title: "Pricing page update for the Workflows tier", labels: ["website"], note: "Add the new tier and the comparison rows it changes." },
        ],
      },
      {
        title: "Website SEO cleanup",
        labels: ["seo"],
        note: "Fix the issues from the September crawl before the launch traffic arrives.",
        children: [
          { title: "Fix duplicate meta descriptions", labels: ["seo"], note: "38 pages share the default description." },
          { title: "Structured data for docs pages", labels: ["seo"], note: "Add Article and BreadcrumbList markup to the docs template." },
        ],
      },
      { title: "Customer story: Northwind Logistics", labels: ["content", "customer"], note: "They cut triage time by 60% after moving support intake to agents." },
      { title: "Webinar: automating triage with agents", labels: ["event"], note: "45-minute session with a live demo and a customer guest." },
      { title: "Refresh the homepage hero copy", labels: ["website", "content"], note: "The current headline still describes the product we sold last year." },
      { title: "October newsletter", labels: ["content"], note: "Product updates, the webinar invite and one customer story." },
      { title: "Comparison page against legacy trackers", labels: ["website", "seo"], note: "Honest feature table plus a migration section." },
      { title: "UTM conventions for paid campaigns", labels: ["analytics"], note: "Every channel tags differently, so attribution reports are unusable." },
      { title: "Booth materials for DevOpsDays", labels: ["event", "design"], note: "Banner, one-pager and a demo loop for the screen." },
      { title: "Social calendar for the next four weeks", labels: ["content"], note: "Three posts a week, tied to the launch timeline." },
      { title: "Clean up HubSpot lifecycle stages", labels: ["analytics"], note: "Contacts sit in custom stages nobody maintains." },
      { title: "Edit the case study video", labels: ["content"], note: "Cut the 40-minute interview into a 2-minute story and three short clips." },
      { title: "Co-marketing brief with Cobalt Cloud", labels: ["partnerships"], note: "Joint webinar and a listing on their marketplace." },
      { title: "Localize landing pages for DACH", labels: ["website"], note: "German versions of the homepage, pricing and the two top landing pages." },
      { title: "Review the G2 profile and screenshots", labels: ["website"], note: "Screenshots are from the old UI and the category is wrong." },
      { title: "Referral program landing page", labels: ["website", "launch"], note: "Explain the reward, link to the referral form, track sign-ups." },
    ],
  },
];

const CRITERIA: Record<string, readonly string[]> = {
  bug: [
    "Reproduced with a failing test before the fix",
    "Fix verified on staging by someone other than the author",
    "Root cause written up in the PR description",
    "No new errors in Sentry for 48 hours after release",
  ],
  feature: [
    "Behind a feature flag until the review",
    "Copy reviewed by design",
    "Works at 380 px wide",
    "Events added to the analytics plan",
    "Docs page updated",
  ],
  infra: [
    "Change applied through Terraform, not the console",
    "Runbook updated",
    "Rollback tested once",
    "Alerting covers the new failure mode",
  ],
  security: [
    "Evidence stored in the compliance folder",
    "Reviewed by a second engineer",
    "Secrets never appear in logs",
  ],
  content: [
    "Draft reviewed by product",
    "Final copy approved by Lena",
    "Links carry UTM parameters",
    "Published and shared in #launches",
  ],
  website: [
    "Lighthouse score stays above 90",
    "Tested on mobile Safari",
    "Copy approved by marketing",
  ],
  other: ["Owner agreed on scope", "Done criteria checked in review", "Stakeholders notified when it ships"],
};

function criteriaFor(labels: string[]): readonly string[] {
  for (const label of labels) {
    if (CRITERIA[label]) return CRITERIA[label];
    if (["seo", "launch", "event"].includes(label)) return CRITERIA.content;
    if (["performance", "tech-debt", "improvement", "accessibility", "design"].includes(label)) return CRITERIA.feature;
  }
  return CRITERIA.other;
}

function describe(template: Omit<Template, "children">): string {
  if (chance(0.08)) return "";
  const pool = [...criteriaFor(template.labels)];
  const criteria: string[] = [];
  const count = Math.min(pool.length, int(2, 3));
  while (criteria.length < count) criteria.push(...pool.splice(Math.floor(random() * pool.length), 1));
  return `${template.note}\n\n**Acceptance criteria**\n${criteria.map((c) => `- ${c}`).join("\n")}`;
}

// ---------------------------------------------------------------------------
// Comment vocabulary
// ---------------------------------------------------------------------------

type Phase = "early" | "active" | "closing";
type Voice = "eng" | "mkt";

const HUMAN_COMMENTS: Record<Voice, Record<Phase, readonly string[]>> = {
  eng: {
    early: [
      "I can pick this up after the release freeze.",
      "Do we have a customer waiting on this, or can it wait for next cycle?",
      "Adding context from the support thread: it started after the September release.",
      "Let's keep the scope tight here and split anything extra into a follow-up.",
    ],
    active: [
      "First pass is up as a draft PR. Still missing tests for the edge cases.",
      "Blocked on access to the staging account, asked in #infra.",
      "Moved the due date: this depends on the review of the parent issue.",
      "Turned out smaller than estimated, should land this week.",
    ],
    closing: [
      "Merged and deployed. Thanks everyone.",
      "Verified on production, closing.",
      "Shipped. Follow-up for the remaining polish is filed separately.",
    ],
  },
  mkt: {
    early: [
      "Can we get this into the launch timeline, or is it a nice-to-have?",
      "Brief is in the shared drive; comments welcome before Thursday.",
      "Sales asked for this twice last month, bumping it up.",
      "Let's agree on the one message before anyone writes copy.",
    ],
    active: [
      "First draft is ready for review, mostly the structure is open.",
      "Waiting on the customer's approval for the quote.",
      "Design is on it this week, I'll keep this issue updated.",
      "Moved the due date to line up with the launch.",
    ],
    closing: [
      "Published. Thanks for the quick reviews.",
      "Live on the site, sharing in #marketing.",
      "Dropped after the launch plan changed, closing it out.",
    ],
  },
};

const AGENT_COMMENTS: Record<Voice, Record<Phase, readonly string[]>> = {
  eng: {
    early: [
      "Triage: reproduced on staging (build 2026.09.4). Linked three related support tickets, all from EU workspaces.",
      "Triage: no open duplicate found. Suggested priority from customer impact: 4 paying workspaces affected.",
      "Collected the related errors from the last 30 days: 412 events across 37 workspaces, rising since Sep 18.",
    ],
    active: [
      "Opened a draft PR with a fix and a regression test. CI is green; waiting on a human review.",
      "Ran the acceptance checks on staging. Two of three pass; the layout still overflows at 380 px.",
      "Dry run finished in 14 minutes with no errors. Logs are attached to the PR.",
    ],
    closing: [
      "Release check: the change is in v2.14.0 and deployed to all regions. No new errors in the 24 hours since.",
      "Verified in production: the failing scenario from the description now passes.",
    ],
  },
  mkt: {
    early: [
      "Pulled the numbers for the brief: last quarter's comparable post drove 1,840 visits and 61 sign-ups.",
      "Collected five customer quotes from recent calls that fit this angle; linked in the brief.",
    ],
    active: [
      "Drafted a first version from the brief. Checked every link: two were broken, fixed in the draft.",
      "Generated three headline variants and scored them against the messaging doc; the second fits best.",
    ],
    closing: [
      "Checked the live page: metadata, UTM links and the sign-up form all work.",
      "Published and scheduled the social posts for the next two weeks.",
    ],
  },
};

// ---------------------------------------------------------------------------
// Issues
// ---------------------------------------------------------------------------

const STATUS_WEIGHTS: Record<Status, number> = {
  backlog: 20,
  todo: 20,
  in_progress: 20,
  in_review: 14,
  done: 20,
  canceled: 5,
};
const PRIORITY_WEIGHTS: Record<Priority, number> = { urgent: 6, high: 20, medium: 34, low: 22, none: 18 };
const FLOW: Status[] = ["todo", "in_progress", "in_review", "done"];
const POINTS = [1, 2, 3, 5, 8] as const;

const issues: Issue[] = [];
let commentSeq = 0;
let activitySeq = 0;

function statusPath(final: Status): Status[] {
  if (final === "backlog") return ["backlog"];
  const start: Status[] = chance(0.5) ? ["backlog"] : [];
  if (final === "canceled") {
    const steps: Status[] = [...start, pick<Status>(["backlog", "todo"]), "canceled"];
    return steps.filter((s, i) => steps.indexOf(s) === i);
  }
  return [...start, ...FLOW.slice(0, FLOW.indexOf(final) + 1)];
}

function makeIssue(seed: ProjectSeed, project: Project, template: Omit<Template, "children">, parent: Issue | null): Issue {
  const final: Status =
    parent?.status === "done" ? (chance(0.85) ? "done" : "canceled") : weighted(STATUS_WEIGHTS);
  const closed = final === "done" || final === "canceled";
  const createdAt = parent
    ? workingHours(Date.parse(parent.createdAt) + int(1, 48) * HOUR)
    : workingHours(AS_OF - int(4, 80) * DAY - int(0, 8) * HOUR);
  const creatorId = chance(0.15) ? pick(AGENTS) : chance(0.5) ? seed.leadId : pick(Object.keys(seed.team));
  const assigneeId = final === "backlog" && chance(0.5) ? null : chance(0.1) ? null : weighted(seed.team);
  const priority: Priority = template.labels.includes("bug") && chance(0.5) ? pick<Priority>(["urgent", "high"]) : weighted(PRIORITY_WEIGHTS);

  // Every event after creation gets an increasing timestamp between creation and the last update.
  const lastAt = closed ? Math.min(AS_OF - int(1, 20) * DAY, createdAt + int(3, 40) * DAY) : AS_OF - int(1, 96) * HOUR;
  const end = Math.max(lastAt, createdAt + 6 * HOUR);
  const path = statusPath(final);
  type Pending = { kind: "status"; from: Status; to: Status } | { kind: "assignee" | "priority" | "due" } | { kind: "comment"; phase: Phase };
  const pending: Pending[] = [];
  if (assigneeId) pending.push({ kind: "assignee" });
  for (let i = 1; i < path.length; i++) pending.push({ kind: "status", from: path[i - 1], to: path[i] });
  if (chance(0.25)) pending.splice(int(0, pending.length), 0, { kind: "priority" });
  for (let n = int(0, closed ? 3 : 4); n > 0; n--) {
    const phase: Phase = n === 1 && closed ? "closing" : pick<Phase>(["early", "active"]);
    const at = phase === "closing" ? pending.length : phase === "early" ? int(0, Math.min(1, pending.length)) : int(0, pending.length);
    pending.splice(at, 0, { kind: "comment", phase });
  }
  const dueDate = chance(0.55)
    ? day(closed ? end + int(-4, 6) * DAY : AS_OF + int(-9, 24) * DAY)
    : null;
  if (dueDate && chance(0.3)) pending.splice(int(0, pending.length), 0, { kind: "due" });
  const times = pending
    .map(() => Math.min(workingHours(createdAt + HOUR + random() * (end - createdAt - HOUR)), AS_OF - HOUR))
    .toSorted((a, b) => a - b)
    .map((t) => Math.round(t / 60_000) * 60_000);

  const issue: Issue = {
    id: `iss_${pad(issues.length + 1)}`,
    projectId: project.id,
    number: project.nextNumber,
    key: `${project.key}-${project.nextNumber}`,
    title: template.title,
    description: describe(template),
    status: final,
    priority,
    assigneeId,
    labels: template.labels,
    dueDate,
    estimate: chance(seed.estimates) ? pick(POINTS) : null,
    parentId: parent?.id ?? null,
    creatorId,
    createdAt: iso(createdAt),
    updatedAt: iso(createdAt),
    comments: [],
    activity: [],
  };
  project.nextNumber += 1;

  const record = (at: number, actorId: string, kind: Activity["kind"], from: string | null, to: string | null) =>
    issue.activity.push({ id: `act_${pad(++activitySeq, 4)}`, actorId, at: iso(at), kind, from, to });
  record(createdAt, creatorId, "created", null, path[0]);

  const teamAgents = Object.keys(seed.team).filter((id) => AGENTS.includes(id));
  const mover = () => (assigneeId && chance(0.8) ? assigneeId : seed.leadId);
  pending.forEach((event, i) => {
    const at = times[i];
    switch (event.kind) {
      case "assignee":
        record(at, chance(0.6) ? seed.leadId : creatorId, "assignee", null, assigneeId);
        break;
      case "status":
        record(at, event.to === "in_progress" || event.to === "in_review" ? mover() : chance(0.5) ? mover() : seed.leadId, "status", event.from, event.to);
        break;
      case "priority": {
        const before = pick(PRIORITIES.filter((p) => p !== priority));
        record(at, seed.leadId, "priority", before, priority);
        break;
      }
      case "due": {
        const before = day(Date.parse(`${dueDate}T12:00:00Z`) - int(3, 10) * DAY);
        record(at, mover(), "due", before, dueDate);
        break;
      }
      case "comment": {
        const agentAssigned = assigneeId !== null && AGENTS.includes(assigneeId);
        const agentVoice = (agentAssigned && chance(0.7)) || chance(0.2);
        const authorId = agentVoice
          ? agentAssigned ? assigneeId : pick(teamAgents)
          : assigneeId && !agentAssigned && chance(0.6) ? assigneeId : seed.leadId;
        const pool = (agentVoice ? AGENT_COMMENTS : HUMAN_COMMENTS)[seed.voice][event.phase];
        const comment: Comment = { id: `cmt_${pad(++commentSeq)}`, authorId, body: pick(pool), createdAt: iso(at) };
        issue.comments.push(comment);
        break;
      }
    }
  });
  issue.updatedAt = iso(Math.max(createdAt, ...times));
  issues.push(issue);
  return issue;
}

const projects: Project[] = PROJECTS.map(({ team: _team, estimates: _estimates, templates: _templates, ...rest }) => ({
  ...rest,
  nextNumber: 1,
}));

for (const [i, seed] of PROJECTS.entries()) {
  const project = projects[i];
  const first = issues.length;
  for (const template of seed.templates) {
    const parent = makeIssue(seed, project, template, null);
    for (const child of template.children ?? []) makeIssue(seed, project, child, parent);
  }
  // Keys follow creation order, as a tracker would have handed them out.
  const created = issues.slice(first).toSorted((a, b) => a.createdAt.localeCompare(b.createdAt));
  created.forEach((issue, n) => {
    issue.number = n + 1;
    issue.key = `${project.key}-${n + 1}`;
  });
  project.nextNumber = created.length + 1;
}

// Ids follow creation order too.
const ordered = issues.toSorted((a, b) => a.createdAt.localeCompare(b.createdAt) || a.key.localeCompare(b.key));
const renamed = new Map(ordered.map((issue, n) => [issue.id, `iss_${pad(n + 1)}`]));
for (const issue of ordered) {
  issue.id = renamed.get(issue.id)!;
  issue.parentId = issue.parentId && renamed.get(issue.parentId)!;
}

const data: TasksData = {
  version: 1,
  asOf: iso(AS_OF),
  viewerId: VIEWER,
  people: PEOPLE,
  projects,
  labels: LABELS,
  issues: ordered,
};

await fs.mkdir(path.dirname(OUT), { recursive: true });
await fs.writeFile(OUT, `${JSON.stringify(data, null, 2)}\n`, "utf-8");
const today = day(AS_OF);
const overdue = issues.filter((i) => i.dueDate && i.dueDate < today && i.status !== "done" && i.status !== "canceled");
const byStatus = Object.fromEntries(Object.keys(STATUS_WEIGHTS).map((s) => [s, issues.filter((i) => i.status === s).length]));
console.log(
  `Wrote ${path.relative(process.cwd(), OUT)}: ${projects.length} projects, ${PEOPLE.length} people, ${issues.length} issues ` +
    `(${Object.entries(byStatus).map(([s, n]) => `${n} ${s}`).join(", ")}), ${overdue.length} overdue, ` +
    `${issues.reduce((n, i) => n + i.comments.length, 0)} comments, ${issues.reduce((n, i) => n + i.activity.length, 0)} activity entries`,
);
