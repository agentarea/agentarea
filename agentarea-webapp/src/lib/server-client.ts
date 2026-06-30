// TODO: Re-enable server-only after fixing client/server separation
// import "server-only";
import {
  createClient,
  createConfig,
  type Client as HeyClient,
} from "@/api/client/client";
import type { ClientOptions } from "@/api/client/types.gen";
import { createClientConfig } from "@/api/client-runtime";

type LegacyParams = {
  path?: Record<string, unknown>;
  query?: Record<string, unknown>;
};

type LegacyRequestOptions = Omit<
  Parameters<HeyClient["request"]>[0],
  "method" | "path" | "query" | "url"
> & {
  params?: LegacyParams;
};

type LegacyMethod = (
  url: string,
  options?: LegacyRequestOptions
) => Promise<{
  data?: unknown;
  error?: unknown;
  response: Response;
}>;

export type ServerClient = {
  DELETE: LegacyMethod;
  GET: LegacyMethod;
  PATCH: LegacyMethod;
  POST: LegacyMethod;
  PUT: LegacyMethod;
};

let serverClient: ServerClient | null = null;

function createServerClient(): ServerClient {
  const client = createClient(
    createClientConfig(createConfig<ClientOptions>())
  );

  const request = async (
    method: "DELETE" | "GET" | "PATCH" | "POST" | "PUT",
    url: string,
    options?: LegacyRequestOptions
  ) => {
    const { params, ...rest } = options ?? {};
    const result = await client.request({
      ...rest,
      method,
      path: params?.path,
      query: params?.query,
      url,
    });

    return {
      data: result.data,
      error: result.error,
      response: result.response as Response,
    };
  };

  return {
    DELETE: (url, options) => request("DELETE", url, options),
    GET: (url, options) => request("GET", url, options),
    PATCH: (url, options) => request("PATCH", url, options),
    POST: (url, options) => request("POST", url, options),
    PUT: (url, options) => request("PUT", url, options),
  };
}

export function getServerClient() {
  if (!serverClient) {
    serverClient = createServerClient();
  }

  return serverClient;
}
