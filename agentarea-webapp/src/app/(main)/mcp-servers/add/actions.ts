"use server";

import { revalidatePath } from "next/cache";
import { redirect } from "next/navigation";
import type {
  McpServerConnectionCreateRequest,
  McpServerCreate,
} from "@/api/client/types.gen";
import { zCreateMcpServerConnectionV1McpServerInstancesWithSpecPostBody } from "@/api/client/zod.gen";
import { getServerClient } from "@/lib/server-client";

export type MCPServerFormValues = {
  type: "docker" | "command" | "external";
  name: string;
  description: string;
  dockerImageUrl?: string;
  version?: string;
  command?: string;
  args?: string;
  endpointUrl?: string;
  headers: Array<{
    key: string;
    value: string;
  }>;
  env?: Array<{
    key: string;
    value: string;
    secret: boolean;
  }>;
  tags?: string;
  isPublic: boolean;
  authConfigId?: string | null;
};

export interface MCPServerFormState {
  message: string;
  errors?: {
    type?: string[];
    name?: string[];
    description?: string[];
    dockerImageUrl?: string[];
    version?: string[];
    command?: string[];
    args?: string[];
    endpointUrl?: string[];
    headers?: Array<{
      key?: string[];
      value?: string[];
    }>;
    tags?: string[];
    isPublic?: string[];
    members?: string[];
    _form?: string[];
  };
  fieldValues?: {
    type: "docker" | "command" | "external";
    name: string;
    description: string;
    dockerImageUrl?: string;
    version?: string;
    command?: string;
    args?: string;
    endpointUrl?: string;
    headers: Array<{
      key: string;
      value: string;
    }>;
    tags: string[];
    isPublic: boolean;
  };
}

function isSecretHeaderName(name: string): boolean {
  const lower = name.toLowerCase();
  return (
    lower === "authorization" ||
    lower === "cookie" ||
    lower === "proxy-authorization" ||
    lower === "x-api-key" ||
    lower.startsWith("x-auth-") ||
    lower.endsWith("-token") ||
    lower.endsWith("-secret") ||
    lower.endsWith("-key")
  );
}

// Mirrors the backend heuristic (MCPServerService._is_secret_env_name) so the
// secret flag is consistent whether it is inferred here or there. The explicit
// per-variable toggle in the form always wins over this fallback.
function isSecretEnvName(name: string): boolean {
  return /(_TOKEN|_SECRET|_KEY|_PASSWORD|_API_KEY|_DSN)$/.test(name.toUpperCase());
}

// Split the editable env rows into the two artifacts the API expects:
//   - env_schema: the *field* definitions, stored on the reusable spec
//     (every named variable, with its secret flag). No values here.
//   - environment: the *values*, stored on the instance. Secret values are
//     routed into the secret manager by the backend based on env_schema.
function splitEnvRows(env: MCPServerFormValues["env"]): {
  envSchema: Array<{ name: string; description: string; isSecret: boolean }>;
  environment: Record<string, string>;
} {
  const rows = (env || [])
    .map((e) => ({ key: e.key.trim(), value: e.value, secret: e.secret }))
    .filter((e) => e.key !== "");

  const envSchema = rows.map((e) => ({
    name: e.key,
    description: `Environment variable ${e.key}`,
    isSecret: e.secret || isSecretEnvName(e.key),
  }));

  const environment: Record<string, string> = {};
  for (const e of rows) {
    if (e.value !== "") environment[e.key] = e.value;
  }

  return { envSchema, environment };
}

function fieldValues(input: MCPServerFormValues): MCPServerFormState["fieldValues"] {
  return {
    type: input.type || "docker",
    name: input.name,
    description: input.description,
    dockerImageUrl: input.dockerImageUrl,
    version: input.version || "1.0.0",
    command: input.command,
    args: input.args,
    endpointUrl: input.endpointUrl,
    headers: input.headers || [],
    tags: input.tags ? [input.tags] : [],
    isPublic: input.isPublic,
  };
}

function toServerConnectionCreate(
  input: MCPServerFormValues
): McpServerConnectionCreateRequest {
  const tags = input.tags ? [input.tags] : [];
  let server: McpServerCreate;
  let instanceJsonSpec: Record<string, unknown> = {};

  if (input.type === "docker") {
    const { envSchema, environment } = splitEnvRows(input.env);
    server = {
      name: input.name,
      description: input.description,
      docker_image_url: input.dockerImageUrl!,
      version: input.version || "1.0.0",
      tags,
      is_public: input.isPublic,
      env_schema: envSchema,
      json_spec: {
        type: "docker",
        image: input.dockerImageUrl!,
      },
    };
    instanceJsonSpec = Object.keys(environment).length ? { environment } : {};
  } else if (input.type === "command") {
    const argsArray = input.args ? input.args.trim().split(/\s+/) : [];
    const { envSchema, environment } = splitEnvRows(input.env);
    server = {
      name: input.name,
      description: input.description,
      version: input.version || "1.0.0",
      tags,
      is_public: input.isPublic,
      env_schema: envSchema,
      cmd: [input.command!, ...argsArray],
      json_spec: {
        type: "command",
        command: input.command!,
        args: argsArray,
      },
    };
    instanceJsonSpec = Object.keys(environment).length ? { environment } : {};
  } else {
    const headersObject: Record<string, string> = {};
    for (const header of input.headers || []) {
      headersObject[header.key] = header.value;
    }

    server = {
      name: input.name,
      description: input.description,
      remote_url: input.endpointUrl!,
      version: input.version || "1.0.0",
      tags,
      is_public: input.isPublic,
      env_schema: Object.keys(headersObject).map((name) => ({
        name,
        description: `HTTP header ${name}`,
        isSecret: isSecretHeaderName(name),
      })),
      json_spec: {
        type: "url",
        endpoint_url: input.endpointUrl!,
      },
    };
    instanceJsonSpec = Object.keys(headersObject).length
      ? { headers: headersObject }
      : {};
  }

  return {
    server,
    instance: {
      name: input.name,
      description: input.description,
      json_spec: instanceJsonSpec,
      ...(input.authConfigId ? { auth_config_id: input.authConfigId } : {}),
    },
  };
}

function mapGeneratedErrors(
  input: MCPServerFormValues,
  issues: Array<{ path: Array<string | number>; message: string }>
): MCPServerFormState {
  const errors: MCPServerFormState["errors"] = {};

  for (const issue of issues) {
    const path = issue.path.join(".");
    if (path.includes("name")) errors.name = [issue.message];
    else if (path.includes("description")) errors.description = [issue.message];
    else if (path.includes("docker_image_url")) errors.dockerImageUrl = [issue.message];
    else if (path.includes("remote_url")) errors.endpointUrl = [issue.message];
    else if (path.includes("cmd")) errors.command = [issue.message];
    else (errors._form ??= []).push(issue.message);
  }

  return {
    message: "Validation failed. Please check the fields.",
    errors: {
      ...errors,
      _form: errors._form ?? ["Please check the fields and try again."],
    },
    fieldValues: fieldValues(input),
  };
}

export async function addMCPServer(
  _prevState: MCPServerFormState,
  input: MCPServerFormValues
): Promise<MCPServerFormState> {
  const hasAuthorizationHeader = input.headers.some(
    (header) => header.key.toLowerCase() === "authorization"
  );
  if (input.authConfigId && hasAuthorizationHeader) {
    return {
      message: "Validation failed. Please check the fields.",
      errors: {
        headers: input.headers.map((header) =>
          header.key.toLowerCase() === "authorization"
            ? { key: ["Remove Authorization when using an auth config."] }
            : {}
        ),
        _form: [
          "Remove the Authorization header or disconnect the selected auth config.",
        ],
      },
      fieldValues: fieldValues(input),
    };
  }

  const body = toServerConnectionCreate(input);
  const validated =
    zCreateMcpServerConnectionV1McpServerInstancesWithSpecPostBody.safeParse(
      body
    );

  if (!validated.success) {
    return mapGeneratedErrors(input, validated.error.issues);
  }

  let response;
  try {
    const client = getServerClient();
    response = await client.POST("/v1/mcp-server-instances/with-spec" as any, {
      body: validated.data,
    } as any);

    if (response.data) {
      revalidatePath("/mcp-servers");
    } else if (response.error) {
      const errorMessage = response.error.detail?.[0]?.msg || "Unknown error";
      return {
        message: `Failed to add server: ${errorMessage}`,
        errors: { _form: [`API Error: ${errorMessage}`] },
        fieldValues: fieldValues(input),
      };
    }
  } catch (error) {
    const errorMessage =
      error instanceof Error ? error.message : "An unexpected error occurred.";
    return {
      message: "An error occurred while adding the MCP server.",
      errors: { _form: [errorMessage] },
      fieldValues: fieldValues(input),
    };
  }

  if (response.data) {
    redirect(`/mcp-servers/${response.data.id}`);
  }

  return {
    message: "Failed to add server after API call.",
    errors: { _form: ["Post-API call check failed."] },
    fieldValues: fieldValues(input),
  };
}
