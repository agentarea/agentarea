import type { SourceCreate } from "@/api/client/types.gen";
import type { SourceType } from "@/lib/sourceTypes";
import type { SourceFormValues, SourceKind } from "./sourceRequest";

/** One event an MCP server lists (MCP Events, SEP-3415). */
export interface McpEvent {
  name: string;
  description?: string;
  delivery: string[];
  inputSchema?: Record<string, unknown>;
}

/** An MCP instance that offers events; `error` set means its listing failed and it cannot be picked. */
export interface McpEventsServer {
  id: string;
  name: string;
  events: McpEvent[];
  error: string | null;
}

export type ArgumentControl =
  | "text"
  | "choice"
  | "switch"
  | "number"
  | "integer"
  | "json";

/** A top-level property of an event's input schema, as one form field. */
export interface ArgumentField {
  key: string;
  label: string;
  description?: string;
  required: boolean;
  control: ArgumentControl;
  options?: string[];
}

export type ArgumentValues = NonNullable<SourceFormValues["arguments"]>;
export type ArgumentProblem = "required" | "number" | "integer" | "json";

const SOURCE_KINDS: SourceKind[] = ["webhook", "poll"];

function record(value: unknown): Record<string, unknown> | undefined {
  return value && typeof value === "object" && !Array.isArray(value)
    ? (value as Record<string, unknown>)
    : undefined;
}

function text(value: unknown): string | undefined {
  return typeof value === "string" && value.trim() ? value : undefined;
}

function parseEvent(raw: unknown): McpEvent[] {
  const entry = record(raw);
  const name = text(entry?.name);
  if (!entry || !name) return [];
  return [
    {
      name,
      description: text(entry.description),
      delivery: Array.isArray(entry.delivery)
        ? entry.delivery.filter((d): d is string => typeof d === "string")
        : [],
      inputSchema: record(entry.inputSchema),
    },
  ];
}

/**
 * The instances that offer MCP Events, from each one's `events` block; one
 * without the block offers none and is left out.
 */
export function mcpEventsServers(
  instances: readonly { id: string; name: string; events?: unknown }[]
): McpEventsServer[] {
  return instances.flatMap((instance) => {
    const offer = record(instance.events);
    if (!offer) return [];
    return [
      {
        id: instance.id,
        name: instance.name,
        events: Array.isArray(offer.events)
          ? offer.events.flatMap(parseEvent)
          : [],
        error: text(offer.error) ?? null,
      },
    ];
  });
}

/** The ways a source can receive `event`: those it lists that a source can be. */
export function mcpEventKinds(event: McpEvent): SourceKind[] {
  return SOURCE_KINDS.filter((kind) => event.delivery.includes(kind));
}

/** The server and event the form points at, when both still exist and the server can be picked. */
export function selectedMcpEvent(
  servers: readonly McpEventsServer[],
  values: SourceFormValues
): { server: McpEventsServer; event: McpEvent | undefined } | undefined {
  const server = servers.find(
    (entry) => entry.id === values.settings.mcp_instance_id && !entry.error
  );
  if (!server) return undefined;
  return {
    server,
    event: server.events.find((entry) => entry.name === values.settings.event),
  };
}

function controlOf(property: Record<string, unknown>): ArgumentControl {
  const options = property.enum;
  if (
    Array.isArray(options) &&
    options.length > 0 &&
    options.every((option) => typeof option === "string")
  ) {
    return "choice";
  }
  switch (property.type) {
    case "string":
      return "text";
    case "boolean":
      return "switch";
    case "number":
      return "number";
    case "integer":
      return "integer";
    default:
      return "json";
  }
}

/** One field per top-level property of `schema`; anything not a plain scalar is edited as JSON. */
export function argumentFields(
  schema: Record<string, unknown> | undefined
): ArgumentField[] {
  const properties = record(schema?.properties);
  if (!properties) return [];
  const required = Array.isArray(schema?.required) ? schema.required : [];
  return Object.entries(properties).map(([key, raw]) => {
    const property = record(raw) ?? {};
    const control = controlOf(property);
    return {
      key,
      label: text(property.title) ?? key,
      description: text(property.description),
      required: required.includes(key),
      control,
      ...(control === "choice" ? { options: property.enum as string[] } : {}),
    };
  });
}

/**
 * The arguments object the form's values make, and what is wrong with each
 * value that does not convert to its field's type. A blank optional field is
 * left out.
 */
export function readArguments(
  fields: readonly ArgumentField[],
  values: ArgumentValues
): {
  arguments: Record<string, unknown>;
  problems: Record<string, ArgumentProblem>;
} {
  const args: Record<string, unknown> = {};
  const problems: Record<string, ArgumentProblem> = {};
  for (const field of fields) {
    const value = values[field.key];
    if (field.control === "switch") {
      if (typeof value === "boolean") args[field.key] = value;
      else if (field.required) args[field.key] = false;
      continue;
    }
    if (typeof value === "boolean") continue;
    const raw = value?.trim() ?? "";
    if (!raw) {
      if (field.required) problems[field.key] = "required";
      continue;
    }
    if (field.control === "number" || field.control === "integer") {
      const parsed = Number(raw);
      if (!Number.isFinite(parsed)) problems[field.key] = "number";
      else if (field.control === "integer" && !Number.isInteger(parsed))
        problems[field.key] = "integer";
      else args[field.key] = parsed;
    } else if (field.control === "json") {
      try {
        args[field.key] = JSON.parse(raw);
      } catch {
        problems[field.key] = "json";
      }
    } else {
      args[field.key] = raw;
    }
  }
  return { arguments: args, problems };
}

/** Whether the form names a server, one of its events, a way in the event offers, and arguments that convert. */
export function mcpEventsReady(
  servers: readonly McpEventsServer[],
  values: SourceFormValues
): boolean {
  const event = selectedMcpEvent(servers, values)?.event;
  if (!event || !values.kind || !mcpEventKinds(event).includes(values.kind)) {
    return false;
  }
  const { problems } = readArguments(
    argumentFields(event.inputSchema),
    values.arguments ?? {}
  );
  return Object.keys(problems).length === 0;
}

/** The create body for an MCP Events source: the server, the event, its arguments as a JSON string, and the chosen way in. */
export function toMcpEventsRequest(
  type: SourceType,
  instanceId: string,
  event: McpEvent,
  values: SourceFormValues
): SourceCreate {
  const { arguments: args } = readArguments(
    argumentFields(event.inputSchema),
    values.arguments ?? {}
  );
  const config: Record<string, string> = {
    mcp_instance_id: instanceId,
    event: event.name,
  };
  if (Object.keys(args).length > 0) config.arguments = JSON.stringify(args);
  return {
    source_type: type.slug,
    kind: values.kind,
    credentials: {},
    config,
  };
}
