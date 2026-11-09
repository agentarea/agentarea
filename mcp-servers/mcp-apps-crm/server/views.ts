import type { Activity, Company, Contact, CrmData, Deal, DealStatus } from "../shared/crm.ts";
import type {
  ActivityRow,
  CompanyRow,
  ContactRow,
  DealCard,
  DealRow,
  PipelineSnapshot,
  SearchResult,
} from "../shared/schema.ts";
import { DAY, Lookup } from "./lookup.ts";

const ownerRef = (lookup: Lookup, id: string) => {
  const owner = lookup.requireOwner(id);
  return { id: owner.id, name: owner.name, handle: owner.handle, kind: owner.kind };
};

export const money = (value: number, currency: string) => `${Math.round(value).toLocaleString("en-US")} ${currency}`;
const days = (from: string, to: string) => Math.max(0, Math.floor((Date.parse(to) - Date.parse(from)) / DAY));

export function dealRow(lookup: Lookup, deal: Deal, now: string): DealRow {
  const stage = lookup.stageOf(deal);
  const company = deal.companyId ? lookup.companies.get(deal.companyId) : undefined;
  const open = lookup.openActivities.get(deal.id) ?? [];
  const next = open[0];
  const enteredAt = deal.stageHistory.at(-1)?.enteredAt ?? deal.createdAt;
  const inStage = days(enteredAt, now);
  return {
    id: deal.id,
    title: deal.title,
    status: deal.status,
    lostReason: deal.lostReason,
    pipelineId: deal.pipelineId,
    stage: { id: stage.id, name: stage.name, probability: stage.probability },
    value: deal.value,
    currency: deal.currency,
    baseValue: lookup.toBase(deal.value, deal.currency),
    company: company ? { id: company.id, name: company.name } : null,
    contacts: deal.contactIds.flatMap((id) => {
      const contact = lookup.contacts.get(id);
      return contact ? [{ id: contact.id, name: contact.name }] : [];
    }),
    owner: ownerRef(lookup, deal.ownerId),
    expectedCloseDate: deal.expectedCloseDate,
    source: deal.source,
    createdAt: deal.createdAt,
    updatedAt: deal.updatedAt,
    closedAt: deal.closedAt,
    daysInStage: inStage,
    rotting: deal.status === "open" && stage.rottenAfterDays !== null && inStage > stage.rottenAfterDays,
    nextActivity: next
      ? { id: next.id, type: next.type, subject: next.subject, dueAt: next.dueAt, overdue: next.dueAt < now }
      : null,
    overdueActivities: open.filter((a) => a.dueAt < now).length,
  };
}

export function companyRow(lookup: Lookup, company: Company): CompanyRow {
  return {
    id: company.id,
    name: company.name,
    domain: company.domain,
    industry: company.industry,
    size: company.size,
    city: company.city,
    owner: ownerRef(lookup, company.ownerId),
    openDeals: lookup.data.deals.filter((d) => d.companyId === company.id && d.status === "open").length,
    contacts: lookup.data.contacts.filter((c) => c.companyId === company.id).length,
  };
}

export function contactRow(lookup: Lookup, contact: Contact): ContactRow {
  const company = contact.companyId ? lookup.companies.get(contact.companyId) : undefined;
  return {
    id: contact.id,
    name: contact.name,
    title: contact.title,
    email: contact.email,
    phone: contact.phone,
    company: company ? { id: company.id, name: company.name } : null,
    owner: ownerRef(lookup, contact.ownerId),
  };
}

export function activityRow(lookup: Lookup, activity: Activity, now: string): ActivityRow {
  const deal = activity.dealId ? lookup.deals.get(activity.dealId) : undefined;
  const contact = activity.contactId ? lookup.contacts.get(activity.contactId) : undefined;
  return {
    id: activity.id,
    type: activity.type,
    subject: activity.subject,
    note: activity.note,
    dueAt: activity.dueAt,
    done: activity.done,
    doneAt: activity.doneAt,
    overdue: !activity.done && activity.dueAt < now,
    deal: deal ? { id: deal.id, name: deal.title } : null,
    contact: contact ? { id: contact.id, name: contact.name } : null,
    owner: ownerRef(lookup, activity.ownerId),
    createdAt: activity.createdAt,
  };
}

export function buildPipelineSnapshot(
  data: CrmData,
  now: string,
  scope: { pipelineId?: string; ownerId?: string },
): PipelineSnapshot {
  const lookup = new Lookup(data);
  const pipeline = lookup.requirePipeline(scope.pipelineId ?? data.pipelines[0].id);
  if (scope.ownerId) lookup.requireOwner(scope.ownerId);
  const deals = data.deals
    .filter((d) => d.pipelineId === pipeline.id && (!scope.ownerId || d.ownerId === scope.ownerId))
    .map((d) => dealRow(lookup, d, now))
    .toSorted((a, b) => b.baseValue - a.baseValue);

  const open = deals.filter((d) => d.status === "open");
  const month = now.slice(0, 7);
  const won = deals.filter((d) => d.status === "won" && d.closedAt?.slice(0, 7) === month);
  const since = Date.parse(now) - 90 * DAY;
  const closed = deals.filter((d) => d.status !== "open" && d.closedAt && Date.parse(d.closedAt) >= since);

  return {
    now,
    generatedAt: new Date().toISOString(),
    account: data.account.name,
    baseCurrency: data.account.baseCurrency,
    fxRates: data.fxRates,
    pipeline: { id: pipeline.id, name: pipeline.name, stages: pipeline.stages },
    pipelines: data.pipelines.map((p) => ({ id: p.id, name: p.name })),
    owners: data.owners,
    ownerId: scope.ownerId ?? null,
    kpis: {
      openValue: open.reduce((sum, d) => sum + d.baseValue, 0),
      openCount: open.length,
      weightedValue: Math.round(open.reduce((sum, d) => sum + d.baseValue * d.stage.probability, 0)),
      wonThisMonth: won.reduce((sum, d) => sum + d.baseValue, 0),
      wonThisMonthCount: won.length,
      winRate: closed.length === 0 ? null : closed.filter((d) => d.status === "won").length / closed.length,
      closedLast90: closed.length,
    },
    columns: pipeline.stages
      .filter((s) => s.outcome === null)
      .map((stage) => {
        const inStage = open.filter((d) => d.stage.id === stage.id);
        const total = inStage.reduce((sum, d) => sum + d.baseValue, 0);
        return { stageId: stage.id, count: inStage.length, total, weighted: Math.round(total * stage.probability) };
      }),
    deals,
    lostReasons: data.lostReasons,
  };
}

export function buildDealCard(data: CrmData, now: string, dealId: string): DealCard {
  const lookup = new Lookup(data);
  const deal = lookup.requireDeal(dealId);
  const pipeline = lookup.requirePipeline(deal.pipelineId);
  const company = deal.companyId ? lookup.companies.get(deal.companyId) : undefined;
  const contacts = deal.contactIds.flatMap((id) => {
    const contact = lookup.contacts.get(id);
    return contact ? [contactRow(lookup, contact)] : [];
  });
  return {
    now,
    generatedAt: new Date().toISOString(),
    baseCurrency: data.account.baseCurrency,
    deal: dealRow(lookup, deal, now),
    stages: pipeline.stages,
    stageHistory: deal.stageHistory.map((visit) => ({
      stageId: visit.stageId,
      stageName: pipeline.stages.find((s) => s.id === visit.stageId)?.name ?? visit.stageId,
      enteredAt: visit.enteredAt,
      leftAt: visit.leftAt,
      days: days(visit.enteredAt, visit.leftAt ?? now),
    })),
    company: company ? companyRow(lookup, company) : null,
    contacts,
    activities: data.activities
      .filter((a) => a.dealId === deal.id)
      .toSorted((a, b) => a.dueAt.localeCompare(b.dueAt))
      .map((a) => activityRow(lookup, a, now)),
    lostReasons: data.lostReasons,
  };
}

export type SearchKind = "deals" | "companies" | "contacts";
export type SearchFilters = {
  query?: string;
  kinds?: SearchKind[];
  stageId?: string;
  ownerId?: string;
  status?: DealStatus;
  overdueActivity?: boolean;
  noNextActivity?: boolean;
  rotting?: boolean;
  limit: number;
};

export function search(data: CrmData, now: string, filters: SearchFilters): SearchResult {
  const lookup = new Lookup(data);
  if (filters.ownerId) lookup.requireOwner(filters.ownerId);
  if (filters.stageId && !data.pipelines.some((p) => p.stages.some((s) => s.id === filters.stageId))) {
    const known = [...new Set(data.pipelines.flatMap((p) => p.stages.map((s) => s.id)))].join(", ");
    throw new Error(`No stage "${filters.stageId}". Known stages: ${known}`);
  }
  const dealOnly =
    filters.stageId !== undefined ||
    filters.status !== undefined ||
    filters.overdueActivity !== undefined ||
    filters.noNextActivity !== undefined ||
    filters.rotting !== undefined;
  const kinds = new Set<SearchKind>(filters.kinds ?? (dealOnly ? ["deals"] : ["deals", "companies", "contacts"]));
  const q = filters.query?.trim().toLowerCase() || null;
  const has = (...fields: (string | undefined | null)[]) => q === null || fields.some((f) => f?.toLowerCase().includes(q));
  const byOwner = (ownerId: string) => !filters.ownerId || ownerId === filters.ownerId;

  const deals = kinds.has("deals")
    ? data.deals
        .filter((deal) => {
          const company = deal.companyId ? lookup.companies.get(deal.companyId) : undefined;
          const people = deal.contactIds.map((id) => lookup.contacts.get(id));
          return (
            byOwner(deal.ownerId) &&
            has(deal.title, company?.name, company?.domain, ...people.flatMap((p) => [p?.name, p?.email]))
          );
        })
        .map((deal) => dealRow(lookup, deal, now))
        .filter(
          (row) =>
            (filters.stageId === undefined || row.stage.id === filters.stageId) &&
            (filters.status === undefined || row.status === filters.status) &&
            (filters.overdueActivity === undefined || row.overdueActivities > 0 === filters.overdueActivity) &&
            (filters.noNextActivity === undefined ||
              (row.status === "open" && (row.nextActivity === null) === filters.noNextActivity)) &&
            (filters.rotting === undefined || row.rotting === filters.rotting),
        )
        .toSorted((a, b) => b.updatedAt.localeCompare(a.updatedAt))
    : [];
  const companies = kinds.has("companies")
    ? data.companies
        .filter((c) => byOwner(c.ownerId) && has(c.name, c.domain, c.industry, c.city))
        .map((c) => companyRow(lookup, c))
    : [];
  const contacts = kinds.has("contacts")
    ? data.contacts
        .filter((c) => {
          const company = c.companyId ? lookup.companies.get(c.companyId) : undefined;
          return byOwner(c.ownerId) && has(c.name, c.email, c.phone, c.title, company?.name);
        })
        .map((c) => contactRow(lookup, c))
    : [];

  return {
    query: filters.query?.trim() || null,
    deals: deals.slice(0, filters.limit),
    companies: companies.slice(0, filters.limit),
    contacts: contacts.slice(0, filters.limit),
    totals: { deals: deals.length, companies: companies.length, contacts: contacts.length },
  };
}

// ---------------------------------------------------------------------------
// Text content: what a model reads next to the structured result.
// ---------------------------------------------------------------------------

const pct = (value: number) => `${Math.round(value * 100)}%`;
const shortDate = (iso: string) => iso.slice(0, 10);

export function describeDeal(row: DealRow): string {
  const state =
    row.status === "open"
      ? `${row.stage.name} (${pct(row.stage.probability)}), ${row.daysInStage}d in stage${row.rotting ? ", rotting" : ""}`
      : row.status === "won"
        ? `won ${row.closedAt ? shortDate(row.closedAt) : ""}`.trim()
        : `lost${row.lostReason ? ` — ${row.lostReason}` : ""}`;
  const next =
    row.status !== "open"
      ? ""
      : row.nextActivity
        ? `; next: ${row.nextActivity.type} “${row.nextActivity.subject}” ${row.nextActivity.overdue ? "OVERDUE since" : "due"} ${shortDate(row.nextActivity.dueAt)}`
        : "; no next activity scheduled";
  return `${row.id} “${row.title}” — ${money(row.value, row.currency)}, ${state}, owner ${row.owner.name}${row.company ? `, ${row.company.name}` : ""}${next}`;
}

export function summarizePipeline(snapshot: PipelineSnapshot): string {
  const { kpis, baseCurrency } = snapshot;
  const owner = snapshot.ownerId ? snapshot.owners.find((o) => o.id === snapshot.ownerId)?.name : "all owners";
  const stages = snapshot.columns
    .map((c) => {
      const stage = snapshot.pipeline.stages.find((s) => s.id === c.stageId)!;
      return `${stage.name} ${c.count} (${money(c.total, baseCurrency)})`;
    })
    .join("; ");
  const open = snapshot.deals.filter((d) => d.status === "open");
  const attention = open.filter((d) => d.overdueActivities > 0 || d.nextActivity === null || d.rotting);
  return [
    `${snapshot.pipeline.name} for ${owner}, as of ${shortDate(snapshot.now)}: ${kpis.openCount} open deals worth ${money(kpis.openValue, baseCurrency)}, weighted forecast ${money(kpis.weightedValue, baseCurrency)}.`,
    `By stage: ${stages}.`,
    `Won this month: ${kpis.wonThisMonthCount} (${money(kpis.wonThisMonth, baseCurrency)}). Win rate over 90 days: ${kpis.winRate === null ? "n/a" : pct(kpis.winRate)} of ${kpis.closedLast90} closed.`,
    attention.length === 0
      ? "Every open deal has a next activity on time."
      : `Needs attention (${attention.length}):\n${attention.map((d) => `- ${describeDeal(d)}`).join("\n")}`,
  ].join("\n");
}

export function summarizeDeal(card: DealCard): string {
  const { deal } = card;
  const done = card.activities.filter((a) => a.done).length;
  const upcoming = card.activities.filter((a) => !a.done);
  return [
    describeDeal(deal),
    card.company ? `Company: ${card.company.name} (${card.company.id}), ${[card.company.industry, card.company.size, card.company.city].filter(Boolean).join(", ")}.` : "No company linked.",
    card.contacts.length > 0
      ? `Contacts: ${card.contacts.map((c) => `${c.name} (${c.id}${c.title ? `, ${c.title}` : ""}${c.email ? `, ${c.email}` : ""})`).join("; ")}.`
      : "No contacts linked.",
    `Expected close: ${deal.expectedCloseDate ?? "not set"}. Source: ${deal.source}.`,
    `Stage history: ${card.stageHistory.map((v) => `${v.stageName} ${v.days}d`).join(" → ")}.`,
    `${done} activities done; ${upcoming.length} open${upcoming.length ? `: ${upcoming.map((a) => `${a.id} ${a.type} “${a.subject}” ${a.overdue ? "overdue since" : "due"} ${shortDate(a.dueAt)}`).join("; ")}` : ""}.`,
  ].join("\n");
}

export function summarizeSearch(result: SearchResult): string {
  const lines: string[] = [];
  const more = (shown: number, total: number) => (total > shown ? ` (showing ${shown} of ${total})` : "");
  if (result.deals.length > 0 || result.totals.deals > 0) {
    lines.push(`Deals${more(result.deals.length, result.totals.deals)}:`, ...result.deals.map((d) => `- ${describeDeal(d)}`));
  }
  if (result.companies.length > 0) {
    lines.push(
      `Companies${more(result.companies.length, result.totals.companies)}:`,
      ...result.companies.map(
        (c) => `- ${c.id} ${c.name}${c.domain ? ` (${c.domain})` : ""}, ${c.openDeals} open deals, owner ${c.owner.name}`,
      ),
    );
  }
  if (result.contacts.length > 0) {
    lines.push(
      `Contacts${more(result.contacts.length, result.totals.contacts)}:`,
      ...result.contacts.map(
        (c) => `- ${c.id} ${c.name}${c.title ? `, ${c.title}` : ""}${c.company ? ` at ${c.company.name}` : ""}${c.email ? `, ${c.email}` : ""}`,
      ),
    );
  }
  return lines.length > 0 ? lines.join("\n") : `Nothing matches${result.query ? ` “${result.query}”` : ""}.`;
}

export function describeActivity(row: ActivityRow): string {
  const target = [row.deal && `deal ${row.deal.id} “${row.deal.name}”`, row.contact && `contact ${row.contact.name}`]
    .filter(Boolean)
    .join(", ");
  const when = row.done ? `done ${shortDate(row.doneAt!)}` : `${row.overdue ? "overdue since" : "due"} ${row.dueAt}`;
  return `${row.id} ${row.type} “${row.subject}” — ${when}, owner ${row.owner.name}${target ? `, ${target}` : ""}`;
}
