export * from "./generated/sdk.gen";
export * from "./generated/types.gen";
export { client } from "./generated/client.gen";
export type TokenProvider = string | (() => string | undefined | Promise<string | undefined>);
export interface ApiClientOptions {
    /** Backend base URL, e.g. http://localhost:8000 */
    baseUrl: string;
    /** Bearer token (static) or a provider resolved per request. */
    token?: TokenProvider;
    /** Override the fetch implementation (defaults to global fetch). */
    fetch?: typeof globalThis.fetch;
}
/**
 * Configure the shared client instance. Call once at startup. Each consumer
 * supplies its own transport: the webapp its Next runtime, the CLI a plain
 * Node runtime with a Bearer token from local config.
 */
export declare function configureApiClient(options: ApiClientOptions): void;
