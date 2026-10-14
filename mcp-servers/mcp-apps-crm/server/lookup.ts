import type { Activity, Company, Contact, CrmData, Deal, Owner, Pipeline, Stage } from "../shared/crm.ts";

export const DAY = 86_400_000;

/** Id lookups over the dataset; the `require*` methods fail with a message a model can act on. */
export class Lookup {
  readonly owners: Map<string, Owner>;
  readonly companies: Map<string, Company>;
  readonly contacts: Map<string, Contact>;
  readonly deals: Map<string, Deal>;
  readonly activities: Map<string, Activity>;
  readonly pipelines: Map<string, Pipeline>;
  /** Not-done activities per deal, soonest first. */
  readonly openActivities = new Map<string, Activity[]>();

  constructor(readonly data: CrmData) {
    this.owners = new Map(data.owners.map((o) => [o.id, o]));
    this.companies = new Map(data.companies.map((c) => [c.id, c]));
    this.contacts = new Map(data.contacts.map((c) => [c.id, c]));
    this.deals = new Map(data.deals.map((d) => [d.id, d]));
    this.activities = new Map(data.activities.map((a) => [a.id, a]));
    this.pipelines = new Map(data.pipelines.map((p) => [p.id, p]));
    for (const activity of data.activities.toSorted((a, b) => a.dueAt.localeCompare(b.dueAt))) {
      if (activity.done || !activity.dealId) continue;
      const list = this.openActivities.get(activity.dealId);
      if (list) list.push(activity);
      else this.openActivities.set(activity.dealId, [activity]);
    }
  }

  requireOwner(id: string): Owner {
    const owner = this.owners.get(id);
    if (!owner) {
      const known = this.data.owners.map((o) => `${o.id} (${o.name}${o.kind === "agent" ? ", agent" : ""})`).join(", ");
      throw new Error(`No owner with id "${id}". Known owners: ${known}`);
    }
    return owner;
  }

  requireCompany(id: string): Company {
    const company = this.companies.get(id);
    if (!company) throw new Error(`No company with id "${id}". Company ids look like "cmp_001"; search_crm finds them.`);
    return company;
  }

  requireContact(id: string): Contact {
    const contact = this.contacts.get(id);
    if (!contact) throw new Error(`No contact with id "${id}". Contact ids look like "ct_001"; search_crm finds them.`);
    return contact;
  }

  requireDeal(id: string): Deal {
    const deal = this.deals.get(id);
    if (!deal) throw new Error(`No deal with id "${id}". Deal ids look like "deal_001"; search_crm or show_pipeline finds them.`);
    return deal;
  }

  requireActivity(id: string): Activity {
    const activity = this.activities.get(id);
    if (!activity) {
      throw new Error(`No activity with id "${id}". Activity ids look like "act_0001"; show_deal lists a deal's activities.`);
    }
    return activity;
  }

  requirePipeline(id: string): Pipeline {
    const pipeline = this.pipelines.get(id);
    if (!pipeline) {
      throw new Error(`No pipeline with id "${id}". Known pipelines: ${this.data.pipelines.map((p) => p.id).join(", ")}`);
    }
    return pipeline;
  }

  requireStage(pipeline: Pipeline, id: string): Stage {
    const stage = pipeline.stages.find((s) => s.id === id);
    if (!stage) {
      throw new Error(`Pipeline "${pipeline.id}" has no stage "${id}". Its stages: ${pipeline.stages.map((s) => s.id).join(", ")}`);
    }
    return stage;
  }

  stageOf(deal: Deal): Stage {
    return this.requireStage(this.requirePipeline(deal.pipelineId), deal.stageId);
  }

  toBase(value: number, currency: Deal["currency"]): number {
    return Math.round(value * this.data.fxRates[currency]);
  }
}
