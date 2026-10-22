import {
  registerAppResource,
  registerAppTool,
  RESOURCE_MIME_TYPE,
} from "@modelcontextprotocol/ext-apps/server";
import type { AppStore } from "@kit/store/store.ts";
import { McpServer, type ReadResourceResult } from "@modelcontextprotocol/server";
import fs from "node:fs/promises";
import path from "node:path";
import { z } from "zod";
import { ACTIVITY_TYPES, COMPANY_SIZES, CURRENCIES, DEAL_STATUSES, OWNER_KINDS } from "../shared/crm.ts";
import {
  activityRowSchema,
  companyRowSchema,
  contactRowSchema,
  dealCardSchema,
  dealRowSchema,
  dealUpdateSchema,
  pipelineSnapshotSchema,
  searchResultSchema,
} from "../shared/schema.ts";
import { Lookup } from "./lookup.ts";
import { CrmStore } from "./store.ts";
import {
  activityRow,
  buildDealCard,
  buildPipelineSnapshot,
  companyRow,
  contactRow,
  dealRow,
  describeActivity,
  describeDeal,
  search,
  summarizeDeal,
  summarizePipeline,
  summarizeSearch,
} from "./views.ts";

export const PIPELINE_URI = "ui://crm/pipeline.html";
export const DEAL_URI = "ui://crm/deal.html";

/** Built views, one single-file HTML each, inside `appDir`. */
const VIEWS = [
  { uri: PIPELINE_URI, name: "Sales pipeline", file: "pipeline.html", description: "Kanban of open deals by stage, with forecast KPIs" },
  { uri: DEAL_URI, name: "Deal card", file: "deal.html", description: "One deal: stage, company, contacts and activity timeline" },
] as const;
export const VIEW_FILES = VIEWS.map((view) => view.file);

/**
 * The app is the view resources plus their tools. The data is not part of
 * it: it lives in `app`, the instance's store; every tool call is one read or
 * one transaction there. `current` is the CRM as of this request, for the
 * owners, stages and sources the tool descriptions name.
 */
export function createServer(app: AppStore, appDir: string, current: CrmStore | null): McpServer {
  const server = new McpServer({ name: "Sales CRM MCP App", version: "0.1.0" });
  if (!current) {
    registerSetup(server, app);
    return server;
  }
  const { data } = current;
  const read = <T>(fn: (store: CrmStore) => T) => app.read((db) => fn(CrmStore.load(db)));
  const write = <T>(fn: (store: CrmStore) => T) =>
    app.transact((db) => {
      const store = CrmStore.load(db);
      const result = fn(store);
      store.save(db);
      return result;
    });
  const owners = data.owners.map((o) => `${o.id} ${o.name}${o.kind === "agent" ? " (AI agent)" : ""}`).join(", ");
  const stages = data.pipelines[0].stages.map((s) => s.id).join(", ");
  const openStages = data.pipelines[0].stages.filter((s) => s.outcome === null).map((s) => s.id).join(", ");
  const ownerId = z.string().describe(`Owner (sales rep) id: ${owners}`);
  const done = (text: string, structuredContent: Record<string, unknown>) => ({
    content: [{ type: "text" as const, text }],
    structuredContent,
  });

  const pipelineInput = z.object({
    owner_id: ownerId.optional().describe(`Show only deals owned by this owner (${owners}). Omit for everyone.`),
    pipeline_id: z.string().optional().describe(`Pipeline id; omit for the default pipeline "${data.pipelines[0].id}"`),
  });

  registerAppTool(
    server,
    "show_pipeline",
    {
      title: "Show sales pipeline",
      description:
        "Open the sales pipeline: open deals by stage with value, owner, days in stage and next activity, plus " +
        "open pipeline value, weighted forecast, won this month and win rate. The text result lists the deals " +
        "that need attention (overdue or missing next activity, rotting in stage).",
      inputSchema: pipelineInput,
      outputSchema: pipelineSnapshotSchema,
      annotations: { readOnlyHint: true },
      _meta: { ui: { resourceUri: PIPELINE_URI } },
    },
    async ({ owner_id, pipeline_id }) =>
      read((store) => {
        const snapshot = buildPipelineSnapshot(store.data, store.now(), { ownerId: owner_id, pipelineId: pipeline_id });
        return done(summarizePipeline(snapshot), snapshot);
      }),
  );

  // Callable by the pipeline view only: it reloads after a filter change or a move.
  registerAppTool(
    server,
    "get_pipeline_snapshot",
    {
      title: "Get pipeline snapshot",
      description: "Pipeline columns, deals and KPIs for one owner filter.",
      inputSchema: pipelineInput,
      outputSchema: pipelineSnapshotSchema,
      annotations: { readOnlyHint: true },
      _meta: { ui: { resourceUri: PIPELINE_URI, visibility: ["app"] } },
    },
    async ({ owner_id, pipeline_id }) =>
      read((store) => {
        const snapshot = buildPipelineSnapshot(store.data, store.now(), { ownerId: owner_id, pipelineId: pipeline_id });
        return done(summarizePipeline(snapshot), snapshot);
      }),
  );

  registerAppTool(
    server,
    "show_deal",
    {
      title: "Show deal",
      description:
        "Open one deal: value, stage and stage history, owner, expected close, company, contacts and the full " +
        "activity timeline (done and upcoming, with activity ids for complete_activity).",
      inputSchema: z.object({
        deal_id: z.string().describe('Deal id, e.g. "deal_001" (show_pipeline and search_crm list them)'),
      }),
      outputSchema: dealCardSchema,
      annotations: { readOnlyHint: true },
      _meta: { ui: { resourceUri: DEAL_URI } },
    },
    async ({ deal_id }) =>
      read((store) => {
        const card = buildDealCard(store.data, store.now(), deal_id);
        return done(summarizeDeal(card), card);
      }),
  );

  server.registerTool(
    "search_crm",
    {
      title: "Search CRM",
      description:
        "Find deals, companies and contacts. `query` matches deal titles, company names and domains, contact " +
        "names, emails and phones (case-insensitive). Deal filters (stage_id, status, overdue_activity, " +
        "no_next_activity, rotting) narrow the search to deals unless `kinds` says otherwise; owner_id applies " +
        "to every kind. Example: open deals nobody has planned a next step for — no_next_activity: true.",
      inputSchema: z.object({
        query: z.string().optional().describe("Text to look for; omit to list by filters only"),
        kinds: z
          .array(z.enum(["deals", "companies", "contacts"]))
          .optional()
          .describe("What to return; defaults to all three, or to deals only when a deal filter is set"),
        stage_id: z.string().optional().describe(`Deals in this stage: ${stages}`),
        status: z.enum(DEAL_STATUSES).optional().describe("Deals with this status"),
        owner_id: ownerId.optional(),
        overdue_activity: z.boolean().optional().describe("true: deals with at least one overdue activity; false: none overdue"),
        no_next_activity: z
          .boolean()
          .optional()
          .describe("true: open deals with no scheduled next activity; false: open deals that have one"),
        rotting: z.boolean().optional().describe("true: open deals stuck in their stage longer than the stage allows"),
        limit: z.number().int().min(1).max(100).optional().describe("Max results per kind (default 25)"),
      }),
      outputSchema: searchResultSchema,
      annotations: { readOnlyHint: true },
    },
    async (input) =>
      read((store) => {
        const result = search(store.data, store.now(), {
          query: input.query,
          kinds: input.kinds,
          stageId: input.stage_id,
          status: input.status,
          ownerId: input.owner_id,
          overdueActivity: input.overdue_activity,
          noNextActivity: input.no_next_activity,
          rotting: input.rotting,
          limit: input.limit ?? 25,
        });
        return done(summarizeSearch(result), result);
      }),
  );

  server.registerTool(
    "create_deal",
    {
      title: "Create deal",
      description:
        "Create a deal in an open stage (the first stage unless stage_id says otherwise). The owner defaults to " +
        "the company's owner. Returns the new deal with its id.",
      inputSchema: z.object({
        title: z.string().min(1).describe('Deal title, e.g. "Volga Logistics — WMS rollout"'),
        value: z.number().min(0).describe("Deal value in `currency`"),
        currency: z.enum(CURRENCIES).optional().describe(`Currency of value; default ${data.account.baseCurrency}`),
        company_id: z.string().optional().describe('Company id, e.g. "cmp_001"'),
        contact_ids: z.array(z.string()).optional().describe('Contact ids on the deal, e.g. ["ct_001"]'),
        owner_id: ownerId.optional().describe(`Owner id (${owners}); required when there is no company_id`),
        pipeline_id: z.string().optional().describe(`Pipeline id; default "${data.pipelines[0].id}"`),
        stage_id: z.string().optional().describe(`Open stage to start in: ${openStages}`),
        expected_close_date: z.string().optional().describe("Expected close date, YYYY-MM-DD"),
        source: z.string().optional().describe(`Where the deal came from, e.g. ${data.sources.join(", ")}`),
      }),
      outputSchema: dealRowSchema,
      annotations: { readOnlyHint: false, idempotentHint: false, destructiveHint: false },
    },
    async (input) =>
      write((store) => {
        const deal = store.createDeal({
          title: input.title,
          value: input.value,
          currency: input.currency,
          companyId: input.company_id,
          contactIds: input.contact_ids,
          ownerId: input.owner_id,
          pipelineId: input.pipeline_id,
          stageId: input.stage_id,
          expectedCloseDate: input.expected_close_date,
          source: input.source,
        });
        const row = dealRow(new Lookup(store.data), deal, store.now());
        return done(`Created ${describeDeal(row)}`, row);
      }),
  );

  server.registerTool(
    "update_deal",
    {
      title: "Update deal",
      description:
        "Change a deal. Moving stage_id records the stage history. status \"won\" or \"lost\" closes the deal " +
        "(lost needs lost_reason); status \"open\" reopens a closed deal in its last open stage or in stage_id. " +
        "Only the fields you pass change; the result lists what changed.",
      inputSchema: z.object({
        deal_id: z.string().describe('Deal id, e.g. "deal_001"'),
        stage_id: z.string().optional().describe(`Move to this stage: ${stages}`),
        status: z.enum(DEAL_STATUSES).optional().describe("open, won or lost"),
        lost_reason: z
          .string()
          .optional()
          .describe(`Why it was lost; required with status "lost". Common: ${data.lostReasons.join("; ")}`),
        title: z.string().optional(),
        value: z.number().min(0).optional().describe("New value in the deal's currency"),
        currency: z.enum(CURRENCIES).optional(),
        owner_id: ownerId.optional(),
        company_id: z.string().nullable().optional().describe("Company id, or null to unlink"),
        contact_ids: z.array(z.string()).optional().describe("Replaces the deal's contacts"),
        expected_close_date: z.string().nullable().optional().describe("YYYY-MM-DD, or null to clear"),
        source: z.string().optional(),
      }),
      outputSchema: dealUpdateSchema,
      annotations: { readOnlyHint: false, idempotentHint: true, destructiveHint: false },
    },
    async (input) =>
      write((store) => {
        const { deal, changes } = store.updateDeal(input.deal_id, {
          stageId: input.stage_id,
          status: input.status,
          lostReason: input.lost_reason,
          title: input.title,
          value: input.value,
          currency: input.currency,
          ownerId: input.owner_id,
          companyId: input.company_id,
          contactIds: input.contact_ids,
          expectedCloseDate: input.expected_close_date,
          source: input.source,
        });
        const row = dealRow(new Lookup(store.data), deal, store.now());
        const text = changes.length > 0 ? `Updated ${deal.id}: ${changes.join("; ")}.\n${describeDeal(row)}` : `No change to ${describeDeal(row)}`;
        return done(text, { deal: row, changes });
      }),
  );

  server.registerTool(
    "create_company",
    {
      title: "Create company",
      description: "Add a company (organization). Fails if a company with the same name exists, naming its id.",
      inputSchema: z.object({
        name: z.string().min(1),
        owner_id: ownerId,
        domain: z.string().optional().describe('Website domain, e.g. "volgalog.ru"'),
        industry: z.string().optional(),
        size: z.enum(COMPANY_SIZES).optional().describe("Headcount band"),
        city: z.string().optional(),
      }),
      outputSchema: companyRowSchema,
      annotations: { readOnlyHint: false, idempotentHint: false, destructiveHint: false },
    },
    async (input) =>
      write((store) => {
        const company = store.createCompany({
          name: input.name,
          ownerId: input.owner_id,
          domain: input.domain,
          industry: input.industry,
          size: input.size,
          city: input.city,
        });
        const row = companyRow(new Lookup(store.data), company);
        return done(`Created company ${row.id} ${row.name}, owner ${row.owner.name}.`, row);
      }),
  );

  server.registerTool(
    "create_contact",
    {
      title: "Create contact",
      description:
        "Add a contact (person), optionally at a company. The owner defaults to the company's owner. Fails if " +
        "the email is already on another contact, naming its id.",
      inputSchema: z.object({
        name: z.string().min(1).describe("Full name"),
        company_id: z.string().optional().describe('Company id, e.g. "cmp_001"'),
        title: z.string().optional().describe("Job title"),
        email: z.string().optional(),
        phone: z.string().optional(),
        owner_id: ownerId.optional().describe(`Owner id (${owners}); required when there is no company_id`),
      }),
      outputSchema: contactRowSchema,
      annotations: { readOnlyHint: false, idempotentHint: false, destructiveHint: false },
    },
    async (input) =>
      write((store) => {
        const contact = store.createContact({
          name: input.name,
          companyId: input.company_id,
          title: input.title,
          email: input.email,
          phone: input.phone,
          ownerId: input.owner_id,
        });
        const row = contactRow(new Lookup(store.data), contact);
        return done(
          `Created contact ${row.id} ${row.name}${row.company ? ` at ${row.company.name}` : ""}, owner ${row.owner.name}.`,
          row,
        );
      }),
  );

  server.registerTool(
    "log_activity",
    {
      title: "Log or schedule activity",
      description:
        "Record a call, email, meeting, task or note on a deal and/or contact. Without due_at it is logged as " +
        "done now. With a future due_at it is scheduled (it becomes the deal's next activity); a past due_at " +
        "logs it as done then. `done` overrides that. The owner defaults to the deal's (or contact's) owner.",
      inputSchema: z.object({
        type: z.enum(ACTIVITY_TYPES),
        subject: z.string().min(1).describe('Short subject, e.g. "Follow-up call on the proposal"'),
        deal_id: z.string().optional().describe('Deal id, e.g. "deal_001"'),
        contact_id: z.string().optional().describe('Contact id, e.g. "ct_001"'),
        due_at: z
          .string()
          .optional()
          .describe("When: ISO 8601 date-time (2026-10-07T10:00:00Z) or a date (2026-10-07, meaning 09:00 UTC)"),
        done: z.boolean().optional().describe("Force done / not done instead of inferring it from due_at"),
        note: z.string().optional().describe("Free-text details or outcome"),
        owner_id: ownerId.optional(),
      }),
      outputSchema: activityRowSchema,
      annotations: { readOnlyHint: false, idempotentHint: false, destructiveHint: false },
    },
    async (input) =>
      write((store) => {
        const activity = store.logActivity({
          type: input.type,
          subject: input.subject,
          dealId: input.deal_id,
          contactId: input.contact_id,
          dueAt: input.due_at,
          done: input.done,
          note: input.note,
          ownerId: input.owner_id,
        });
        const row = activityRow(new Lookup(store.data), activity, store.now());
        return done(`${row.done ? "Logged" : "Scheduled"} ${describeActivity(row)}.`, row);
      }),
  );

  server.registerTool(
    "complete_activity",
    {
      title: "Complete activity",
      description: "Mark an activity done (or, with done: false, not done again).",
      inputSchema: z.object({
        activity_id: z.string().describe('Activity id, e.g. "act_0001" (show_deal lists them)'),
        done: z.boolean().optional().describe("Default true"),
      }),
      outputSchema: activityRowSchema,
      annotations: { readOnlyHint: false, idempotentHint: true, destructiveHint: false },
    },
    async ({ activity_id, done: isDone }) =>
      write((store) => {
        const { activity, changed } = store.completeActivity(activity_id, isDone ?? true);
        const row = activityRow(new Lookup(store.data), activity, store.now());
        return done(`${changed ? "Updated" : "Already so"}: ${describeActivity(row)}.`, row);
      }),
  );

  server.registerTool(
    "add_owner",
    {
      title: "Add owner",
      description: "Add a sales rep, human or AI agent, who can then own companies, contacts, deals and activities.",
      inputSchema: ownerFields,
      annotations: { readOnlyHint: false, idempotentHint: false, destructiveHint: false },
    },
    async (fields) =>
      write((store) => {
        const owner = store.addOwner(fields);
        return { content: [{ type: "text" as const, text: `Added owner ${owner.id} ${owner.name} (${owner.kind}).` }] };
      }),
  );

  for (const view of VIEWS) {
    registerAppResource(
      server,
      view.name,
      view.uri,
      { mimeType: RESOURCE_MIME_TYPE, description: view.description },
      async (): Promise<ReadResourceResult> => ({
        contents: [
          {
            uri: view.uri,
            mimeType: RESOURCE_MIME_TYPE,
            text: await fs.readFile(path.join(appDir, view.file), "utf-8"),
          },
        ],
      }),
    );
  }

  return server;
}

const ownerFields = z.object({
  name: z.string().min(1).describe("Full name"),
  title: z.string().optional().describe("Role, e.g. Account Executive"),
  email: z.string().optional(),
  kind: z.enum(OWNER_KINDS).optional().describe("human or agent, default human"),
});

/** An instance whose storage holds no CRM yet offers one tool: the one that writes it. */
function registerSetup(server: McpServer, app: AppStore): void {
  server.registerTool(
    "setup_crm",
    {
      title: "Set up CRM",
      description:
        "This CRM is empty. Write the account, its currencies, the sales owners and the pipeline stages; " +
        "the other tools appear once it is set up. Owners can be added later.",
      inputSchema: z.object({
        account: z.string().min(1).describe("Company whose CRM this is"),
        base_currency: z.enum(CURRENCIES).describe("Currency forecasts and totals are shown in"),
        usd_rate: z.number().positive().describe("Price of one USD in RUB, e.g. 92"),
        owners: z.array(ownerFields).min(1),
        stages: z.array(z.string().min(1)).min(1).optional().describe("Open stage names, first to last; Won and Lost are added. Default: Lead in, Qualified, Proposal sent, Negotiation"),
        sources: z.array(z.string().min(1)).optional().describe("Lead sources deals can name"),
        lost_reasons: z.array(z.string().min(1)).optional().describe("Reasons a deal can be lost with"),
      }),
      annotations: { readOnlyHint: false, idempotentHint: false, destructiveHint: false },
    },
    async ({ base_currency, usd_rate, lost_reasons, ...rest }) => {
      const store = await app.transact((db) =>
        CrmStore.setup(db, { ...rest, baseCurrency: base_currency, usdRate: usd_rate, lostReasons: lost_reasons }),
      );
      const { owners, pipelines } = store.data;
      return {
        content: [
          {
            type: "text" as const,
            text:
              `Set up ${store.data.account.name}: ${owners.length} owner${owners.length === 1 ? "" : "s"}, ` +
              `stages ${pipelines[0].stages.map((s) => s.name).join(" → ")}. Reconnect to see the CRM tools.`,
          },
        ],
      };
    },
  );
}
