"use server";

import { revalidatePath } from "next/cache";
import { redirect } from "next/navigation";
import { z } from "zod";
import { createMCPServer, createMCPServerInstance } from "@/lib/api";

// Define the header schema for external servers
const HeaderSchema = z.object({
  key: z.string().min(1, "Header key is required"),
  value: z.string().min(1, "Header value is required"),
});

// Define the schema for validation
const MCPServerSchema = z
  .object({
    type: z.enum(["docker", "external"], {
      required_error: "Server type is required",
    }),
    name: z.string().min(1, "Server name is required"),
    description: z.string().min(1, "Description is required"),
    // Docker-specific fields
    dockerImageUrl: z.string().optional(),
    version: z.string().optional(),
    // External-specific fields
    endpointUrl: z.string().optional(),
    headers: z.array(HeaderSchema).optional().default([]),
    // Common fields
    tags: z.string().optional(),
    isPublic: z.boolean(),
  })
  .refine(
    (data) => {
      // Validate docker-specific fields when type is docker
      if (data.type === "docker") {
        return data.dockerImageUrl && data.dockerImageUrl.length > 0;
      }
      // Validate external-specific fields when type is external
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
    endpointUrl?: string[];
    headers?: Array<{
      key?: string[];
      value?: string[];
    }>;
    tags?: string[];
    isPublic?: string[];
    _form?: string[]; // General form errors
  };
  fieldValues?: {
    type: "docker" | "external";
    name: string;
    description: string;
    dockerImageUrl?: string;
    version?: string;
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
    type: formData.get("type") as "docker" | "external",
    name: formData.get("name") as string,
    description: formData.get("description") as string,
    dockerImageUrl: formData.get("dockerImageUrl") as string,
    version: (formData.get("version") as string) || "1.0.0",
    endpointUrl: formData.get("endpointUrl") as string,
    headers,
    tags: formData.get("tags") as string,
    isPublic: formData.get("isPublic") === "true",
  };

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
        endpointUrl: rawFormData.endpointUrl,
        headers: rawFormData.headers,
        tags: rawFormData.tags ? [rawFormData.tags] : [],
        isPublic: rawFormData.isPublic,
      },
    };
  }

  let response;
  try {
    if (validatedFields.data.type === "docker") {
      // Create Docker-based MCP Server
      response = await createMCPServer({
        name: validatedFields.data.name,
        description: validatedFields.data.description,
        docker_image_url: validatedFields.data.dockerImageUrl!,
        version: validatedFields.data.version || "1.0.0",
        tags: validatedFields.data.tags ? [validatedFields.data.tags] : [],
        is_public: validatedFields.data.isPublic,
        env_schema: [],
      });
    } else {
      // Create External MCP Server Instance
      const jsonSpec: Record<string, unknown> = {
        endpoint_url: validatedFields.data.endpointUrl!,
        is_public: validatedFields.data.isPublic,
      };

      if (
        validatedFields.data.headers &&
        validatedFields.data.headers.length > 0
      ) {
        jsonSpec.headers = validatedFields.data.headers.reduce(
          (acc, header) => ({ ...acc, [header.key]: header.value }),
          {}
        );
      }

      if (validatedFields.data.tags) {
        jsonSpec.tags = [validatedFields.data.tags];
      }

      response = await createMCPServerInstance({
        name: validatedFields.data.name,
        description: validatedFields.data.description,
        server_spec_id: null,
        json_spec: jsonSpec,
      });
    }

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
    redirect("/mcp-servers");
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
