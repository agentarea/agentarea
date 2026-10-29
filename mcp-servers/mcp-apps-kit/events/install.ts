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
import {
  challenge,
  checkSubscription,
  isKnownEndpoint,
  parseSubscribeParams,
  parseUnsubscribeParams,
  subscribe,
  subscriptionId,
  unsubscribe,
  type EventDispatcher,
} from "./subscriptions.ts";

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

/**
 * Advertises the events extension and answers events/list and events/poll from `app`'s log.
 * With a `dispatcher` (one per process, over the same app) it also takes webhook
 * subscriptions; the app's MIGRATIONS must then include EVENT_SUBSCRIPTIONS_MIGRATION.
 */
export function installEvents(
  server: McpServer,
  options: { app: AppStore; types: readonly EventType<never>[]; ProtocolError: ProtocolErrorClass; dispatcher?: EventDispatcher },
): void {
  const { app, types, ProtocolError, dispatcher } = options;
  const answer = async <T>(fn: () => Promise<T>): Promise<T> => {
    try {
      return await fn();
    } catch (error) {
      if (error instanceof EventsError) throw new ProtocolError(error.code, error.message, error.data);
      throw error;
    }
  };
  server.server.registerCapabilities({ extensions: { [EVENTS_EXTENSION]: EVENTS_SETTINGS } });
  server.server.setRequestHandler("events/list", { params: schema((value) => value ?? {}) }, () =>
    listEvents(types, dispatcher ? ["poll", "webhook"] : ["poll"]),
  );
  server.server.setRequestHandler("events/poll", { params: schema(parsePollParams) }, (params) =>
    answer(() => app.read((db) => pollEvents(db, types, params))),
  );
  if (!dispatcher) return;
  server.server.setRequestHandler("events/subscribe", { params: schema(parseSubscribeParams) }, (params) =>
    answer(async () => {
      checkSubscription(types, params);
      // A new endpoint, or a new secret for it, proves it wants deliveries before anything is stored.
      if (!(await app.read((db) => isKnownEndpoint(db, params)))) {
        await challenge(dispatcher.fetch, { url: params.url, secret: params.secret, id: subscriptionId(params.name, params.arguments, params.url) });
      }
      const grant = await app.transact((db) => subscribe(db, types, params));
      dispatcher.kick();
      return grant;
    }),
  );
  server.server.setRequestHandler("events/unsubscribe", { params: schema(parseUnsubscribeParams) }, (params) =>
    answer(async () => {
      await app.transact((db) => unsubscribe(db, params));
      return {};
    }),
  );
}
