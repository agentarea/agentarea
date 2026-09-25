import {
  registerAppResource,
  registerAppTool,
  RESOURCE_MIME_TYPE,
} from "@modelcontextprotocol/ext-apps/server";
import { McpServer, type ReadResourceResult } from "@modelcontextprotocol/server";
import fs from "node:fs/promises";
import path from "node:path";
import { z } from "zod";
import {
  enrolledContactSchema,
  handledReplySchema,
  leadCardSchema,
  snapshotSchema,
  type EnrolledContact,
  type HandledReply,
} from "../shared/schema.ts";
import { buildLeadCard, summarizeLead } from "./lead.ts";
import { buildSnapshot, summarize } from "./snapshot.ts";
import type { OutreachStore } from "./store.ts";

export const DASHBOARD_URI = "ui://outreach/dashboard.html";
export const LEAD_URI = "ui://outreach/lead.html";

/** Built views, one single-file HTML each, inside `appDir`. */
const VIEWS = [
  { uri: DASHBOARD_URI, name: "Outreach dashboard", file: "dashboard.html", description: "Interactive B2B outbound dashboard" },
  { uri: LEAD_URI, name: "Lead card", file: "lead.html", description: "One lead: signal, sequence, thread and next step" },
] as const;
export const VIEW_FILES = VIEWS.map((view) => view.file);

const periodSchema = z
  .union([z.literal(7), z.literal(30), z.literal(90)])
  .describe("Length of the reporting period in days");

/**
 * The app is the view resources plus their tools. The data is not part of
 * it: `store` is the dataset bound by whoever runs the server.
 */
export function createServer(store: OutreachStore, appDir: string): McpServer {
  const server = new McpServer({ name: "Outreach MCP App", version: "0.1.0" });
  const campaignIds = store.data.campaigns.map((c) => c.id).join(", ");

  registerAppTool(
    server,
    "show_outreach_dashboard",
    {
      title: "Show outreach dashboard",
      description:
        "Open the B2B outbound dashboard: buying signals, sequences, replies, meetings and pipeline for the last 30 days. " +
        `Optionally focus on one campaign (${campaignIds}).`,
      inputSchema: z.object({
        campaign: z.string().optional().describe(`Campaign id to focus on: ${campaignIds}. Omit for all campaigns.`),
      }),
      outputSchema: snapshotSchema,
      annotations: { readOnlyHint: true },
      _meta: { ui: { resourceUri: DASHBOARD_URI } },
    },
    async ({ campaign }) => {
      const snapshot = buildSnapshot(store.data, campaign ?? null, 30);
      return { content: [{ type: "text", text: summarize(snapshot) }], structuredContent: snapshot };
    },
  );

  // The tools below are callable by the dashboard only: a click in the UI runs
  // them directly, without a model turn in between.
  registerAppTool(
    server,
    "get_outreach_snapshot",
    {
      title: "Get outreach snapshot",
      description: "KPIs, funnel, signals, replies and people for one period and campaign.",
      inputSchema: z.object({
        campaign: z.string().optional().describe(`Campaign id: ${campaignIds}. Omit for all campaigns.`),
        days: periodSchema.optional(),
      }),
      outputSchema: snapshotSchema,
      annotations: { readOnlyHint: true },
      _meta: { ui: { resourceUri: DASHBOARD_URI, visibility: ["app"] } },
    },
    async ({ campaign, days }) => {
      const snapshot = buildSnapshot(store.data, campaign ?? null, days ?? 30);
      return { content: [{ type: "text", text: summarize(snapshot) }], structuredContent: snapshot };
    },
  );

  registerAppTool(
    server,
    "add_to_sequence",
    {
      title: "Add to sequence",
      description: "Enroll a contact into a campaign's email sequence; step 1 is scheduled.",
      inputSchema: z.object({
        contactId: z.string(),
        campaign: z.string().describe(`Campaign id: ${campaignIds}`),
      }),
      outputSchema: enrolledContactSchema,
      annotations: { readOnlyHint: false, idempotentHint: false },
      _meta: { ui: { resourceUri: DASHBOARD_URI, visibility: ["app"] } },
    },
    async ({ contactId, campaign }) => {
      const contact = store.enroll(contactId, campaign);
      await store.persist();
      const account = store.data.accounts.find((a) => a.id === contact.accountId);
      const result: EnrolledContact = {
        id: contact.id,
        name: `${contact.firstName} ${contact.lastName}`,
        company: account?.name ?? "",
        campaign: { id: campaign, name: store.data.campaigns.find((c) => c.id === campaign)!.name },
        status: "scheduled",
        step: 1,
        enrolledAt: contact.enrollment!.enrolledAt,
      };
      return {
        content: [{ type: "text", text: `${result.name} (${result.company}) added to ${result.campaign.name}; step 1 scheduled.` }],
        structuredContent: result,
      };
    },
  );

  registerAppTool(
    server,
    "mark_reply_handled",
    {
      title: "Mark reply handled",
      description: "Mark a reply as handled so it leaves the inbox queue.",
      inputSchema: z.object({ replyId: z.string() }),
      outputSchema: handledReplySchema,
      annotations: { readOnlyHint: false, idempotentHint: true },
      _meta: { ui: { resourceUri: DASHBOARD_URI, visibility: ["app"] } },
    },
    async ({ replyId }) => {
      const reply = store.markHandled(replyId);
      await store.persist();
      const result: HandledReply = { id: reply.id, handled: true, handledAt: reply.handledAt! };
      return { content: [{ type: "text", text: `Reply ${reply.id} marked handled.` }], structuredContent: result };
    },
  );

  registerAppTool(
    server,
    "show_lead_card",
    {
      title: "Show lead card",
      description:
        "Open the card for one lead: company, the buying signal that triggered outreach, sequence progress, " +
        "the full email thread with their reply, and the suggested next step.",
      inputSchema: z.object({
        contact_id: z.string().describe('Contact id, e.g. "ct_042" (the dashboard shows them)'),
      }),
      outputSchema: leadCardSchema,
      annotations: { readOnlyHint: true },
      _meta: { ui: { resourceUri: LEAD_URI } },
    },
    async ({ contact_id }) => {
      const card = buildLeadCard(store.data, contact_id);
      return { content: [{ type: "text", text: summarizeLead(card) }], structuredContent: card };
    },
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
