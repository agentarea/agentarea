import { client } from "./generated/client.gen";
import { fillWorkspace, isWorkspaceScoped } from "./workspace-url";

// Public surface of the shared AgentArea API client (fetch flavor).
// Generated SDK functions + types come from ./generated; the transport
// (base URL + auth) is injected by each consumer via configureApiClient().

export * from "./generated/sdk.gen";
export * from "./generated/types.gen";
export { client } from "./generated/client.gen";
export {
  fillWorkspace,
  InvalidWorkspaceError,
  isWorkspaceScoped,
  MissingWorkspaceError,
} from "./workspace-url";

export type TokenProvider =
  | string
  | (() => string | undefined | Promise<string | undefined>);

export interface ApiClientOptions {
  /** Backend base URL, e.g. http://localhost:8000 */
  baseUrl: string;
  /** Bearer token (static) or a provider resolved per request. */
  token?: TokenProvider;
  /** Override the fetch implementation (defaults to global fetch). */
  fetch?: typeof globalThis.fetch;
  /**
   * Slug for `/v1/workspaces/{workspace}/...` endpoints, asked only when a
   * request is workspace-scoped. Returning nothing fails that request.
   */
  workspace?: () => string | undefined | Promise<string | undefined>;
}

/**
 * Configure the shared client instance. Call once at startup. Each consumer
 * supplies its own transport: the webapp its Next runtime, the CLI a plain
 * Node runtime with a Bearer token from local config.
 */
export function configureApiClient(options: ApiClientOptions): void {
  client.setConfig({
    baseUrl: options.baseUrl,
    ...(options.fetch ? { fetch: options.fetch } : {}),
  });

  if (options.token !== undefined) {
    client.interceptors.request.use(async (request: Request) => {
      const token =
        typeof options.token === "function"
          ? await options.token()
          : options.token;
      if (token) {
        request.headers.set("Authorization", `Bearer ${token}`);
      }
      return request;
    });
  }

  client.interceptors.request.use(async (request: Request) => {
    if (!isWorkspaceScoped(request.url)) return request;
    const url = fillWorkspace(request.url, await options.workspace?.());
    // A Request's URL is read-only; rebuild it around the buffered body.
    return new Request(url, {
      method: request.method,
      headers: request.headers,
      body: request.body ? await request.arrayBuffer() : undefined,
      redirect: request.redirect,
      signal: request.signal,
    });
  });
}
