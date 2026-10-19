import { describe, expect, it } from "vitest";
import type { SourceType } from "@/lib/sourceTypes";
import {
  argumentFields,
  mcpEventKinds,
  mcpEventsReady,
  mcpEventsServers,
  readArguments,
  toMcpEventsRequest,
} from "./mcpEventsSource";
import type { SourceFormValues } from "./sourceRequest";

const ticketCreated = {
  name: "ticket.created",
  description: "Fires when a ticket is opened in a queue",
  delivery: ["poll", "webhook"],
  inputSchema: {
    type: "object",
    required: ["queue"],
    properties: {
      queue: { type: "string", description: "Queue to watch" },
      priority: { type: "string", enum: ["low", "high"] },
      limit: { type: "integer" },
      urgent: { type: "boolean" },
      filter: { type: "object" },
    },
  },
};

const instances = [
  {
    id: "i-1",
    name: "helpdesk",
    events: {
      extension: "io.modelcontextprotocol/events",
      events: [
        ticketCreated,
        { name: "ticket.closed", delivery: ["poll", "push"] },
        { description: "no name" },
      ],
    },
  },
  { id: "i-2", name: "broken", events: { events: [], error: "timed out" } },
  { id: "i-3", name: "plain", events: null },
];

const type = { slug: "mcp_events" } as SourceType;

function form(values: Partial<SourceFormValues>): SourceFormValues {
  return { secrets: {}, settings: {}, templates: {}, ...values };
}

describe("mcpEventsServers", () => {
  it("keeps only instances that offer events, with the listing error and named events", () => {
    const servers = mcpEventsServers(instances);
    expect(servers.map((s) => [s.id, s.error])).toEqual([
      ["i-1", null],
      ["i-2", "timed out"],
    ]);
    expect(servers[0].events.map((e) => e.name)).toEqual([
      "ticket.created",
      "ticket.closed",
    ]);
  });
});

describe("mcpEventKinds", () => {
  it("offers only the ways a source can be that the event lists", () => {
    const [created, closed] = mcpEventsServers(instances)[0].events;
    expect(mcpEventKinds(created)).toEqual(["webhook", "poll"]);
    expect(mcpEventKinds(closed)).toEqual(["poll"]);
  });
});

describe("argumentFields + readArguments", () => {
  const fields = argumentFields(ticketCreated.inputSchema);

  it("maps each top-level property to a control, nested ones to JSON", () => {
    expect(fields.map((f) => [f.key, f.control, f.required])).toEqual([
      ["queue", "text", true],
      ["priority", "choice", false],
      ["limit", "integer", false],
      ["urgent", "switch", false],
      ["filter", "json", false],
    ]);
    expect(fields[1].options).toEqual(["low", "high"]);
  });

  it("converts values to their types and leaves blank optional ones out", () => {
    expect(
      readArguments(fields, {
        queue: " support ",
        limit: "5",
        urgent: false,
        filter: '{"tag":"vip"}',
        priority: "",
      })
    ).toEqual({
      arguments: {
        queue: "support",
        limit: 5,
        urgent: false,
        filter: { tag: "vip" },
      },
      problems: {},
    });
  });

  it("names what does not convert and a required value left blank", () => {
    expect(
      readArguments(fields, { limit: "1.5", filter: "{nope" }).problems
    ).toEqual({ queue: "required", limit: "integer", filter: "json" });
  });
});

describe("toMcpEventsRequest", () => {
  const servers = mcpEventsServers(instances);
  const values = form({
    kind: "poll",
    settings: { mcp_instance_id: "i-1", event: "ticket.created" },
    arguments: { queue: "support" },
  });

  it("is ready only with a server that can be picked, a listed event, an offered way in and valid arguments", () => {
    expect(mcpEventsReady(servers, values)).toBe(true);
    expect(mcpEventsReady(servers, { ...values, kind: undefined })).toBe(false);
    expect(mcpEventsReady(servers, { ...values, arguments: {} })).toBe(false);
    expect(
      mcpEventsReady(servers, {
        ...values,
        settings: { mcp_instance_id: "i-2", event: "ticket.created" },
      })
    ).toBe(false);
    expect(
      mcpEventsReady(servers, {
        ...values,
        kind: "webhook",
        settings: { mcp_instance_id: "i-1", event: "ticket.closed" },
      })
    ).toBe(false);
  });

  it("sends the arguments as a JSON string, no credentials, and the chosen way in", () => {
    expect(
      toMcpEventsRequest(type, "i-1", servers[0].events[0], values)
    ).toEqual({
      source_type: "mcp_events",
      kind: "poll",
      credentials: {},
      config: {
        mcp_instance_id: "i-1",
        event: "ticket.created",
        arguments: '{"queue":"support"}',
      },
    });
  });
});
