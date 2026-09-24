import {
  FUNNEL_STAGES,
  REPLY_CLASS_KIND,
  REPLY_CLASSES,
  type Contact,
  type Enrollment,
  type FunnelStage,
  type Meeting,
  type OutreachData,
  type Period,
  type PersonStatus,
  type Reply,
  type ReplyClass,
  type Signal,
  type Touch,
} from "../shared/outreach.ts";
import type {
  FunnelStageRow,
  Kpi,
  PersonRow,
  ReplyRow,
  SequenceState,
  SeriesPoint,
  SignalRef,
  SignalRow,
  Snapshot,
  ThreadMessage,
} from "../shared/schema.ts";

export const DAY = 86_400_000;

const FUNNEL_LABELS: Record<FunnelStage, string> = {
  signals: "Signals",
  qualified: "Qualified",
  contacted: "Contacted",
  opened: "Opened",
  replied: "Replied",
  positive: "Positive",
  meeting: "Meeting",
};

type Window = { start: number; end: number };

const within = (iso: string, { start, end }: Window) => {
  const at = Date.parse(iso);
  return at > start && at <= end;
};

export const shortDate = (iso: string) =>
  new Date(iso).toLocaleDateString("en-US", { weekday: "short", month: "short", day: "numeric", timeZone: "UTC" });

/** Lookups over the dataset, built once per snapshot or card. */
export class Index {
  readonly accounts;
  readonly contacts;
  readonly campaigns;
  readonly signals;
  readonly touches = new Map<string, Touch[]>();
  readonly replies = new Map<string, Reply>();
  readonly meetings = new Map<string, Meeting>();

  constructor(readonly data: OutreachData) {
    this.accounts = new Map(data.accounts.map((a) => [a.id, a]));
    this.contacts = new Map(data.contacts.map((c) => [c.id, c]));
    this.campaigns = new Map(data.campaigns.map((c) => [c.id, c]));
    this.signals = new Map(data.signals.map((s) => [s.id, s]));
    for (const touch of [...data.touches].sort((a, b) => a.sentAt.localeCompare(b.sentAt))) {
      const list = this.touches.get(touch.contactId);
      if (list) list.push(touch);
      else this.touches.set(touch.contactId, [touch]);
    }
    for (const reply of data.replies) {
      const existing = this.replies.get(reply.contactId);
      if (!existing || reply.receivedAt < existing.receivedAt) this.replies.set(reply.contactId, reply);
    }
    for (const meeting of data.meetings) this.meetings.set(meeting.contactId, meeting);
  }

  touchesOf(contactId: string): Touch[] {
    return this.touches.get(contactId) ?? [];
  }

  campaignRef(id: string) {
    const campaign = this.campaigns.get(id);
    return { id, name: campaign?.name ?? id };
  }

  /** How far one person got, judged from the signal that enrolled them. */
  stageOf(contact: Contact): FunnelStage {
    const touches = this.touchesOf(contact.id);
    if (touches.length === 0) return "qualified";
    if (this.meetings.has(contact.id)) return "meeting";
    const reply = this.replies.get(contact.id);
    if (reply && REPLY_CLASS_KIND[reply.classification] === "positive") return "positive";
    if (reply && REPLY_CLASS_KIND[reply.classification] !== "auto") return "replied";
    if (touches.some((t) => t.openedAt)) return "opened";
    return "contacted";
  }

  /** The signal that put this person into their sequence. */
  enrollmentSignal(contact: Contact): Signal | undefined {
    return contact.enrollment?.signalId ? this.signals.get(contact.enrollment.signalId) : undefined;
  }

  signalRef(contact: Contact): SignalRef | null {
    const signal = this.enrollmentSignal(contact);
    return signal
      ? { type: signal.type, description: signal.description, strength: signal.strength, detectedAt: signal.detectedAt }
      : null;
  }

  /** Where an enrolled person stands in their sequence. */
  sequenceState(contact: Contact & { enrollment: Enrollment }): SequenceState {
    const sequence = this.campaigns.get(contact.enrollment.campaignId)?.sequence ?? [];
    const touches = this.touchesOf(contact.id);
    const reply = this.replies.get(contact.id);
    const kind = reply ? REPLY_CLASS_KIND[reply.classification] : null;
    const step = touches.length;
    const stopped = kind !== null && kind !== "auto";
    const next = !stopped && step > 0 && step < sequence.length ? sequence[step] : undefined;
    const status: PersonStatus =
      reply?.classification === "unsubscribe"
        ? "unsubscribed"
        : this.meetings.has(contact.id)
          ? "meeting"
          : stopped
            ? "replied"
            : step === 0
              ? "scheduled"
              : step >= sequence.length
                ? "finished"
                : "in_sequence";
    return {
      step,
      totalSteps: sequence.length,
      lastTouchAt: touches.at(-1)?.sentAt ?? null,
      nextTouchAt: next ? new Date(Date.parse(touches[0].sentAt) + next.dayOffset * DAY).toISOString() : null,
      status,
    };
  }

  /** Our emails to this person, each followed by any reply that answered it. */
  thread(contact: Contact, until?: string): ThreadMessage[] {
    const name = `${contact.firstName} ${contact.lastName}`;
    const from = `${this.data.sender.name} · ${this.data.sender.company}`;
    const touches = this.touchesOf(contact.id).filter((t) => until === undefined || t.sentAt <= until);
    const replies = this.data.replies
      .filter((r) => r.contactId === contact.id && (until === undefined || r.receivedAt <= until))
      .toSorted((a, b) => a.receivedAt.localeCompare(b.receivedAt));
    const messages: ThreadMessage[] = [
      ...touches.map((t) => ({
        direction: "outbound" as const,
        step: t.step,
        from,
        subject: t.subject,
        body: t.body,
        at: t.sentAt,
        openedAt: t.openedAt,
        clickedAt: t.clickedAt,
      })),
      ...replies.map((r) => {
        const answered = touches.find((t) => t.id === r.touchId) ?? touches.filter((t) => t.sentAt <= r.receivedAt).at(-1);
        return {
          direction: "inbound" as const,
          step: null,
          from: name,
          subject: answered ? `Re: ${answered.subject.replace(/^Re: /, "")}` : "Re:",
          body: r.body,
          at: r.receivedAt,
          openedAt: null,
          clickedAt: null,
        };
      }),
    ];
    return messages.toSorted((a, b) => a.at.localeCompare(b.at));
  }
}

function kpis(index: Index, campaign: string | null, window: Window) {
  const inCampaign = (campaignId: string) => campaign === null || campaignId === campaign;
  const { data } = index;

  const signals = data.signals.filter((s) => inCampaign(s.campaignId) && within(s.detectedAt, window)).length;

  let contacted = 0;
  const touchedInWindow = new Set<string>();
  for (const [contactId, touches] of index.touches) {
    const scoped = touches.filter((t) => inCampaign(t.campaignId));
    if (scoped.length === 0) continue;
    if (within(scoped[0].sentAt, window)) contacted += 1;
    if (scoped.some((t) => within(t.sentAt, window))) touchedInWindow.add(contactId);
  }

  const replies = data.replies.filter((r) => inCampaign(r.campaignId) && within(r.receivedAt, window));
  const repliers = new Set(
    replies
      .filter((r) => REPLY_CLASS_KIND[r.classification] !== "auto" && touchedInWindow.has(r.contactId))
      .map((r) => r.contactId),
  );
  const meetings = data.meetings.filter((m) => inCampaign(m.campaignId) && within(m.bookedAt, window));

  return {
    signals,
    contacted,
    reply_rate: touchedInWindow.size === 0 ? 0 : repliers.size / touchedInWindow.size,
    positive: replies.filter((r) => REPLY_CLASS_KIND[r.classification] === "positive").length,
    meetings: meetings.length,
    pipeline: meetings.reduce((sum, m) => sum + m.pipelineValue, 0),
  };
}

export function suggestedNextStep(reply: Reply, contact: Contact, signal: Signal | undefined, meeting: Meeting | undefined): string {
  switch (reply.classification) {
    case "interested":
      return `Send the one-page overview and pricing ranges today, and offer two slots this week.${signal ? ` Keep the “${signal.description}” angle — it's why they answered.` : ""}`;
    case "meeting_booked":
      return `Confirm the call${meeting ? ` for ${shortDate(meeting.scheduledFor)}` : ""}, send a two-line agenda and prep a demo built around ${contact.firstName}'s signal.`;
    case "referral":
      return `Email the referred colleague within 24 hours, mention ${contact.firstName}'s intro in the first line and keep ${contact.firstName} in cc.`;
    case "not_now":
      return `Stop the sequence and set a check-in for ${shortDate(new Date(Date.parse(reply.receivedAt) + 45 * DAY).toISOString())}. Log the timing in the CRM.`;
    case "objection":
      return `Answer the objection head-on in three sentences and attach one customer proof point from a similar team. Don't push for a meeting yet.`;
    case "out_of_office":
      return `No action needed — the sequence resumes automatically once ${contact.firstName} is back.`;
    case "unsubscribe":
      return `${contact.firstName} is suppressed from all sequences. No further outreach.`;
  }
}

export function buildSnapshot(data: OutreachData, campaign: string | null, days: Period): Snapshot {
  const index = new Index(data);
  if (campaign !== null && !index.campaigns.has(campaign)) {
    throw new Error(`Unknown campaign "${campaign}". Known: ${data.campaigns.map((c) => c.id).join(", ")}`);
  }
  const inCampaign = (campaignId: string) => campaign === null || campaignId === campaign;
  const asOf = Date.parse(data.asOf);
  const current: Window = { start: asOf - days * DAY, end: asOf };
  const previous: Window = { start: asOf - 2 * days * DAY, end: current.start };
  const hasBaseline = previous.start >= Date.parse(data.historyStart);

  const now = kpis(index, campaign, current);
  const before = hasBaseline ? kpis(index, campaign, previous) : null;
  const kpiRows: Kpi[] = (
    [
      ["signals", "Signals detected", "number"],
      ["contacted", "Contacted", "number"],
      ["reply_rate", "Reply rate", "percent"],
      ["positive", "Positive replies", "number"],
      ["meetings", "Meetings booked", "number"],
      ["pipeline", "Pipeline created", "currency"],
    ] as const
  ).map(([key, label, format]) => ({ key, label, format, value: now[key], previous: before ? before[key] : null }));

  // Funnel: the cohort of signals detected in the period, followed forward.
  const cohort = data.signals.filter((s) => inCampaign(s.campaignId) && within(s.detectedAt, current));
  const reached: Record<FunnelStage, number> = Object.fromEntries(FUNNEL_STAGES.map((s) => [s, 0])) as Record<
    FunnelStage,
    number
  >;
  const peopleIds: string[] = [];
  for (const signal of cohort) {
    reached.signals += 1;
    if (!signal.qualified) continue;
    reached.qualified += 1;
    const contact = index.contacts.get(signal.contactId);
    if (!contact || contact.enrollment?.signalId !== signal.id) continue;
    peopleIds.push(contact.id);
    const stage = index.stageOf(contact);
    for (const key of FUNNEL_STAGES.slice(2, FUNNEL_STAGES.indexOf(stage) + 1)) reached[key] += 1;
  }
  const funnel: FunnelStageRow[] = FUNNEL_STAGES.map((key, i) => {
    const prior = i === 0 ? null : reached[FUNNEL_STAGES[i - 1]];
    return {
      key,
      label: FUNNEL_LABELS[key],
      count: reached[key],
      conversion: prior === null ? null : prior === 0 ? 0 : reached[key] / prior,
    };
  });

  const signals: SignalRow[] = cohort
    .toSorted((a, b) => b.detectedAt.localeCompare(a.detectedAt))
    .map((signal) => {
      const account = index.accounts.get(signal.accountId)!;
      const contact = index.contacts.get(signal.contactId)!;
      return {
        id: signal.id,
        type: signal.type,
        description: signal.description,
        strength: signal.strength,
        detectedAt: signal.detectedAt,
        qualified: signal.qualified,
        status: contact.enrollment ? "in_sequence" : "not_contacted",
        campaign: index.campaignRef(signal.campaignId),
        account: {
          name: account.name,
          domain: account.domain,
          industry: account.industry,
          employees: account.employees,
          region: account.region,
        },
        contact: { id: contact.id, name: `${contact.firstName} ${contact.lastName}`, title: contact.title },
      };
    });

  const replies: ReplyRow[] = data.replies
    .filter((r) => inCampaign(r.campaignId) && within(r.receivedAt, current))
    .toSorted((a, b) => b.receivedAt.localeCompare(a.receivedAt))
    .map((reply) => {
      const contact = index.contacts.get(reply.contactId)!;
      const account = index.accounts.get(contact.accountId)!;
      const meeting = index.meetings.get(contact.id);
      return {
        id: reply.id,
        receivedAt: reply.receivedAt,
        classification: reply.classification,
        handled: reply.handled,
        body: reply.body,
        contact: { id: contact.id, name, title: contact.title, email: contact.email },
        account: { name: account.name, domain: account.domain, industry: account.industry },
        campaign: index.campaignRef(reply.campaignId),
        signal: index.signalRef(contact),
        thread: index.thread(contact, reply.receivedAt),
        suggestedNextStep: suggestedNextStep(reply, contact, index.enrollmentSignal(contact), meeting),
        meeting: meeting ? { scheduledFor: meeting.scheduledFor, pipelineValue: meeting.pipelineValue } : null,
      };
    });

  const people: PersonRow[] = peopleIds
    .map((id) => index.contacts.get(id)!)
    .map((contact) => {
      const account = index.accounts.get(contact.accountId)!;
      const enrollment = contact.enrollment!;
      const reply = index.replies.get(contact.id);
      return {
        contactId: contact.id,
        name: `${contact.firstName} ${contact.lastName}`,
        title: contact.title,
        company: account.name,
        domain: account.domain,
        campaign: index.campaignRef(enrollment.campaignId),
        signal: index.signalRef(contact),
        ...index.sequenceState({ ...contact, enrollment }),
        replyClass: reply?.classification ?? null,
        stage: index.stageOf(contact),
      };
    })
    .toSorted((a, b) => (b.lastTouchAt ?? "9").localeCompare(a.lastTouchAt ?? "9"));

  const series: SeriesPoint[] = [];
  const byDay = new Map<string, SeriesPoint>();
  for (let i = days - 1; i >= 0; i--) {
    const date = new Date(asOf - i * DAY).toISOString().slice(0, 10);
    const point = { date, ...Object.fromEntries(REPLY_CLASSES.map((c) => [c, 0])) } as SeriesPoint;
    series.push(point);
    byDay.set(date, point);
  }
  for (const reply of replies) {
    const point = byDay.get(reply.receivedAt.slice(0, 10));
    if (point) point[reply.classification as ReplyClass] += 1;
  }

  return {
    asOf: data.asOf,
    generatedAt: new Date().toISOString(),
    period: days,
    campaign,
    campaigns: data.campaigns.map((c) => ({ id: c.id, name: c.name, persona: c.persona })),
    sender: { name: data.sender.name, company: data.sender.company },
    kpis: kpiRows,
    funnel,
    signals,
    replies,
    people,
    series,
  };
}

export function summarize(snapshot: Snapshot): string {
  const value = (key: Kpi["key"]) => snapshot.kpis.find((k) => k.key === key)!.value;
  const scope = snapshot.campaign
    ? (snapshot.campaigns.find((c) => c.id === snapshot.campaign)?.name ?? snapshot.campaign)
    : "all campaigns";
  const open = snapshot.replies.filter((r) => !r.handled).length;
  const waiting = snapshot.signals.filter((s) => s.qualified && s.status === "not_contacted").length;
  return [
    `Outbound over the last ${snapshot.period} days (${scope}), as of ${snapshot.asOf.slice(0, 10)}:`,
    `${value("signals")} buying signals, ${value("contacted")} people contacted, ${Math.round(value("reply_rate") * 100)}% reply rate,`,
    `${value("positive")} positive replies, ${value("meetings")} meetings booked, $${Math.round(value("pipeline") / 1000)}k pipeline.`,
    `${open} replies need handling; ${waiting} qualified signals are not in a sequence yet.`,
  ].join(" ");
}
