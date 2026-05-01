"use server";

import { revalidatePath } from "next/cache";
import { redirect } from "next/navigation";
import { z } from "zod";
import { getServerClient } from "@/lib/server-client";

// Define the header schema for external servers
const HeaderSchema = z.object({
  key: z.string().min(1, "Header key is required"),
  value: z.string().min(1, "Header value is required"),
});

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

// Define the schema for validation
const MCPServerSchema = z
  .object({
    type: z.enum(["docker", "command", "external"], {
      required_error: "Server type is required",
    }),
    name: z.string().min(1, "Server name is required"),
    description: z.string().min(1, "Description is required"),
    // Docker-specific fields
    dockerImageUrl: z.string().optional(),
    version: z.string().optional(),
    // Command-specific fields
    command: z.string().optional(),
    args: z.string().optional(),
    // External-specific fields
    endpointUrl: z.string().optional(),
    headers: z.array(HeaderSchema).optional().default([]),
    // Common fields
    tags: z.string().optional(),
    isPublic: z.boolean(),
    members: z.string().optional(), // JSON-stringified array of instance IDs
  })
  .refine(
    (data) => {
      if (data.type === "docker") {
        return data.dockerImageUrl && data.dockerImageUrl.length > 0;
      }
      if (data.type === "command") {
        return data.command && data.command.length > 0;
      }
      if (data.type === "external") {
        return data.endpointUrl && data.endpointUrl.length > 0;
      }
      return true;
    },
    {
      message: "Required fields missing for selected server type",
      path: ["type"],
    }
  );

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
    _form?: string[]; // General form errors
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

export async function addMCPServer(
  prevState: MCPServerFormState,
  formData: FormData
): Promise<MCPServerFormState> {
  // Extract header data from FormData for external servers
  const headerKeys: string[] = [];
  const headerValues: string[] = [];

  for (const [key, value] of formData.entries()) {
    if (key.startsWith("headers.") && key.endsWith(".key")) {
      headerKeys.push(value as string);
    }
    if (key.startsWith("headers.") && key.endsWith(".value")) {
      headerValues.push(value as string);
    }
  }

  const headers = headerKeys.map((key, index) => ({
    key,
    value: headerValues[index] || "",
  }));

  const rawFormData = {
    type: formData.get("type") as "docker" | "command" | "external",
    name: formData.get("name") as string,
    description: formData.get("description") as string,
    dockerImageUrl: formData.get("dockerImageUrl") as string,
    version: (formData.get("version") as string) || "1.0.0",
    command: formData.get("command") as string,
    args: formData.get("args") as string,
    endpointUrl: formData.get("endpointUrl") as string,
    headers,
    tags: formData.get("tags") as string,
    isPublic: formData.get("isPublic") === "true",
    members: formData.get("members") as string | undefined,
  };

  // Extract auth config ID (not part of Zod validation, optional)
  const authConfigId = formData.get("authConfigId") as string | null;

  const validatedFields = MCPServerSchema.safeParse(rawFormData);

  if (!validatedFields.success) {
    console.error(
      "Validation Errors:",
      validatedFields.error.flatten().fieldErrors
    );

    const errorsByPath = validatedFields.error.flatten().fieldErrors;
    return {
      message: "Validation failed. Please check the fields.",
      errors: {
        type: errorsByPath.type,
        name: errorsByPath.name,
        description: errorsByPath.description,
        dockerImageUrl: errorsByPath.dockerImageUrl,
        version: errorsByPath.version,
        command: errorsByPath.command,
        args: errorsByPath.args,
        endpointUrl: errorsByPath.endpointUrl,
        tags: errorsByPath.tags,
        isPublic: errorsByPath.isPublic,
        _form: ["Please check the fields and try again."],
      },
      fieldValues: {
        type: rawFormData.type || "docker",
        name: rawFormData.name,
        description: rawFormData.description,
        dockerImageUrl: rawFormData.dockerImageUrl,
        version: rawFormData.version,
        command: rawFormData.command,
        args: rawFormData.args,
        endpointUrl: rawFormData.endpointUrl,
        headers: rawFormData.headers,
        tags: rawFormData.tags ? [rawFormData.tags] : [],
        isPublic: rawFormData.isPublic,
      },
    };
  }

  const hasAuthorizationHeader = headers.some(
    (header) => header.key.toLowerCase() === "authorization"
  );
  if (authConfigId && hasAuthorizationHeader) {
    return {
      message: "Validation failed. Please check the fields.",
      errors: {
        headers: headers.map((header) =>
          header.key.toLowerCase() === "authorization"
            ? { key: ["Remove Authorization when using an auth config."] }
            : {}
        ),
        _form: ["Remove the Authorization header or disconnect the selected auth config."],
      },
      fieldValues: {
        type: rawFormData.type || "external",
        name: rawFormData.name,
        description: rawFormData.description,
        dockerImageUrl: rawFormData.dockerImageUrl,
        version: rawFormData.version,
        command: rawFormData.command,
        args: rawFormData.args,
        endpointUrl: rawFormData.endpointUrl,
        headers: rawFormData.headers,
        tags: rawFormData.tags ? [rawFormData.tags] : [],
        isPublic: rawFormData.isPublic,
      },
    };
  }

  let response;
  try {
    const tags = validatedFields.data.tags ? [validatedFields.data.tags] : [];
    let serverPayload: Record<string, unknown>;
    let instanceJsonSpec: Record<string, unknown> = {};

    if (validatedFields.data.type === "docker") {
      serverPayload = {
        name: validatedFields.data.name,
        description: validatedFields.data.description,
        docker_image_url: validatedFields.data.dockerImageUrl!,
        version: validatedFields.data.version || "1.0.0",
        tags,
        is_public: validatedFields.data.isPublic,
        env_schema: [],
        json_spec: {
          type: "docker",
          image: validatedFields.data.dockerImageUrl!,
        },
      };
    } else if (validatedFields.data.type === "command") {
      const argsArray = validatedFields.data.args
        ? validatedFields.data.args.trim().split(/\s+/)
        : [];
      serverPayload = {
        name: validatedFields.data.name,
        description: validatedFields.data.description,
        version: validatedFields.data.version || "1.0.0",
        tags,
        is_public: validatedFields.data.isPublic,
        env_schema: [],
        cmd: [validatedFields.data.command!, ...argsArray],
        json_spec: {
          type: "command",
          command: validatedFields.data.command!,
          args: argsArray,
        },
      };
    } else {
      const headersObject: Record<string, string> = {};
      if (
        validatedFields.data.headers &&
        validatedFields.data.headers.length > 0
      ) {
        for (const header of validatedFields.data.headers) {
          headersObject[header.key] = header.value;
        }
      }
      serverPayload = {
        name: validatedFields.data.name,
        description: validatedFields.data.description,
        remote_url: validatedFields.data.endpointUrl!,
        version: validatedFields.data.version || "1.0.0",
        tags,
        is_public: validatedFields.data.isPublic,
        env_schema: Object.keys(headersObject).map((name) => ({
          name,
          description: `HTTP header ${name}`,
          isSecret: isSecretHeaderName(name),
        })),
        json_spec: {
          type: "url",
          endpoint_url: validatedFields.data.endpointUrl!,
        },
      };
      instanceJsonSpec = Object.keys(headersObject).length
        ? { headers: headersObject }
        : {};
    }

    const instancePayload = {
      name: validatedFields.data.name,
      description: validatedFields.data.description,
      json_spec: instanceJsonSpec,
      ...(authConfigId ? { auth_config_id: authConfigId } : {}),
    };
    const client = getServerClient();
    response = await client.POST("/v1/mcp-server-instances/with-spec" as any, {
      body: {
        server: serverPayload,
        instance: instancePayload,
      },
    } as any);

    if (response.data) {
      console.log("MCP server added successfully:", response.data);
      revalidatePath("/mcp-servers");
    } else if (response.error) {
      console.error("Failed to add MCP server:", response.error);
      const errorMessage = response.error.detail?.[0]?.msg || "Unknown error";
      return {
        message: `Failed to add server: ${errorMessage}`,
        errors: { _form: [`API Error: ${errorMessage}`] },
        fieldValues: {
          type: validatedFields.data.type,
          name: validatedFields.data.name,
          description: validatedFields.data.description,
          dockerImageUrl: validatedFields.data.dockerImageUrl,
          version: validatedFields.data.version,
          command: validatedFields.data.command,
          args: validatedFields.data.args,
          endpointUrl: validatedFields.data.endpointUrl,
          headers: validatedFields.data.headers || [],
          tags: validatedFields.data.tags ? [validatedFields.data.tags] : [],
          isPublic: validatedFields.data.isPublic,
        },
      };
    }
  } catch (error) {
    console.error("Error adding MCP server:", error);
    let errorMessage = "An unexpected error occurred.";
    if (error instanceof Error) {
      errorMessage = error.message;
    }
    return {
      message: "An error occurred while adding the MCP server.",
      errors: { _form: [errorMessage] },
      fieldValues: {
        type: validatedFields.data.type,
        name: validatedFields.data.name,
        description: validatedFields.data.description,
        dockerImageUrl: validatedFields.data.dockerImageUrl,
        version: validatedFields.data.version,
        endpointUrl: validatedFields.data.endpointUrl,
        headers: validatedFields.data.headers || [],
        tags: validatedFields.data.tags ? [validatedFields.data.tags] : [],
        isPublic: validatedFields.data.isPublic,
      },
    };
  }

  if (response.data) {
    redirect(`/mcp-servers/${response.data.id}`);
  } else {
    return {
      message: "Failed to add server after API call.",
      errors: { _form: ["Post-API call check failed."] },
      fieldValues: {
        type: validatedFields.data.type,
        name: validatedFields.data.name,
        description: validatedFields.data.description,
        dockerImageUrl: validatedFields.data.dockerImageUrl,
        version: validatedFields.data.version,
        endpointUrl: validatedFields.data.endpointUrl,
        headers: validatedFields.data.headers || [],
        tags: validatedFields.data.tags ? [validatedFields.data.tags] : [],
        isPublic: validatedFields.data.isPublic,
      },
    };
  }
}
