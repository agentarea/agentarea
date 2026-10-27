/**
 * Serves an app's event log as MCP Events on its McpServer.
 *
 * The kit has no node_modules of its own and the app's bundler cannot resolve
 * packages from here, so the SDK is a type import only and the app hands in
 * its ProtocolError class.
 */
import type { McpServer } from "@modelcontextprotocol/server";
import type { AppStore } from "../store/store.ts";
import { EVENTS_EXTENSION, EVENTS_SETTINGS, EventsError, listEvents, parsePollParams, pollEvents, type EventType } from "./protocol.ts";

type ProtocolErrorClass = new (code: number, message: string, data?: unknown) => Error;

/** A Standard Schema over a parse function, as the SDK validates custom-method params with. */
const schema = <T>(parse: (value: unknown) => T) => ({
  "~standard": {
    version: 1 as const,
    vendor: "agentarea-mcp-apps-kit",
    types: undefined as unknown as { input: unknown; output: T },
    validate: (value: unknown) => {
      try {
        return { value: parse(value) };
      } catch (error) {
        return { issues: [{ message: (error as Error).message }] };
      }
    },
  },
});

/** Advertises the events extension and answers events/list and events/poll from `app`'s log. */
export function installEvents(
  server: McpServer,
  options: { app: AppStore; types: readonly EventType<never>[]; ProtocolError: ProtocolErrorClass },
): void {
  const { app, types, ProtocolError } = options;
  server.server.registerCapabilities({ extensions: { [EVENTS_EXTENSION]: EVENTS_SETTINGS } });
  server.server.setRequestHandler("events/list", { params: schema((value) => value ?? {}) }, () => listEvents(types));
  server.server.setRequestHandler("events/poll", { params: schema(parsePollParams) }, async (params) => {
    try {
      return await app.read((db) => pollEvents(db, types, params));
    } catch (error) {
      if (error instanceof EventsError) throw new ProtocolError(error.code, error.message, error.data);
      throw error;
    }
  });
}
