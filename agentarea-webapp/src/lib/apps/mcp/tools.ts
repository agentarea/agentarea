import type { ReadResourceResult, Tool } from "@modelcontextprotocol/client";
import { ToolSchema } from "@modelcontextprotocol/core";
import {
  McpUiResourceMetaSchema,
  McpUiToolMetaSchema,
  RESOURCE_MIME_TYPE,
  type McpUiResourceCsp,
  type McpUiResourcePermissions,
} from "@modelcontextprotocol/ext-apps/app-bridge";
import type { McpServerInstanceResponse } from "@/api/client/types.gen";

/**
 * Who asks for a tool: the host starting an app, the app calling a tool, or an
 * app opening another UI of its connection through an app link.
 */
export type McpAppCaller = "host" | "app" | "link";

/** A model-visible tool that renders an MCP App. */
export type McpAppEntry = {
  instanceId: string;
  instanceName: string;
  toolName: string;
  title?: string;
  description: string;
  resourceUri: string;
  requiresInput: boolean;
};

export type McpAppUiResource = {
  uri: string;
  html: string;
  csp?: McpUiResourceCsp;
  permissions?: McpUiResourcePermissions;
  prefersBorder?: boolean;
};

// Stored tools are whatever the server advertised at verification; a tool
// that is not a valid MCP tool is not offered at all.
function storedTools(instance: McpServerInstanceResponse): Tool[] {
  const raw = instance.tools?.length
    ? instance.tools
    : instance.json_spec.available_tools;
  if (!Array.isArray(raw)) return [];
  return raw.flatMap((candidate) => {
    const parsed = ToolSchema.safeParse(candidate);
    return parsed.success ? [parsed.data] : [];
  });
}

/**
 * Audiences allowed to use a tool, and its UI resource. Visibility defaults to
 * both audiences; malformed `_meta.ui` admits nobody, like the agent-side
 * filter in agentarea_agents_sdk.tools.mcp_app_ui.
 */
function toolUi(tool: Tool): {
  visibility: readonly string[];
  resourceUri?: string;
} {
  const parsed = McpUiToolMetaSchema.safeParse(tool._meta?.ui ?? {});
  if (!parsed.success) return { visibility: [] };
  const { visibility = ["model", "app"], resourceUri } = parsed.data;
  return {
    visibility,
    resourceUri: resourceUri?.startsWith("ui://") ? resourceUri : undefined,
  };
}

/**
 * The UI resource of a tool that opens an app, or undefined. Only a tool the
 * model may see opens an app; app-only tools serve an app that is already open.
 */
function entryResourceUri(tool: Tool): string | undefined {
  const ui = toolUi(tool);
  return ui.visibility.includes("model") ? ui.resourceUri : undefined;
}

/**
 * Why a connection cannot serve MCP Apps, or null. Bundles proxy member tool
 * calls but not the members' `ui://` resources; an unverified connection has
 * no tool list to trust.
 */
function unavailableReason(instance: McpServerInstanceResponse): string | null {
  if (instance.json_spec.type === "bundle") {
    return "MCP bundle connections cannot serve MCP Apps";
  }
  if (instance.verification.status !== "succeeded") {
    return "This connection has not been verified";
  }
  return null;
}

/** Apps a workspace can open: model-visible tools with a UI resource. */
export function mcpAppEntries(
  instances: readonly McpServerInstanceResponse[]
): McpAppEntry[] {
  return instances.flatMap((instance) => {
    if (unavailableReason(instance)) return [];
    return storedTools(instance).flatMap((tool) => {
      const resourceUri = entryResourceUri(tool);
      if (!resourceUri) return [];
      const required = tool.inputSchema?.required;
      return [
        {
          instanceId: instance.id,
          instanceName: instance.name,
          toolName: tool.name,
          title: tool.title,
          description: tool.description ?? "",
          resourceUri,
          requiresInput: Array.isArray(required) && required.length > 0,
        },
      ];
    });
  });
}

/**
 * The stored tool a caller may invoke, or a thrown reason why not. The host
 * may start only an app's entry tool; an app may call any tool visible to
 * apps; an app link may open only an entry tool that is also visible to apps,
 * so a link cannot reach a tool the app could not call itself.
 */
export function resolveMcpAppTool(
  instance: McpServerInstanceResponse,
  toolName: string,
  caller: McpAppCaller
): Tool {
  const unavailable = unavailableReason(instance);
  if (unavailable) throw new Error(unavailable);
  const tool = storedTools(instance).find((entry) => entry.name === toolName);
  if (!tool) {
    throw new Error(`Tool "${toolName}" is not exposed by this connection`);
  }
  if (caller !== "host" && !toolUi(tool).visibility.includes("app")) {
    throw new Error(`Tool "${toolName}" is not callable from an MCP App`);
  }
  if (caller !== "app" && !entryResourceUri(tool)) {
    throw new Error(`Tool "${toolName}" is not an MCP App entry point`);
  }
  return tool;
}

/**
 * Arguments for a tool from an app link's query values, which are all
 * strings: each one is converted to the type the tool's input schema declares
 * for it. A value that does not convert is refused rather than passed on.
 */
export function mcpAppLinkArguments(
  tool: Tool,
  params: Readonly<Record<string, string>>
): Record<string, unknown> {
  const properties = tool.inputSchema.properties ?? {};
  return Object.fromEntries(
    Object.entries(params).map(([name, value]) => {
      const declared = properties[name];
      const type =
        typeof declared === "object" && declared !== null && "type" in declared
          ? declared.type
          : undefined;
      if (type === "integer" || type === "number") {
        const parsed = Number(value);
        if (
          value.trim() === "" ||
          !Number.isFinite(parsed) ||
          (type === "integer" && !Number.isInteger(parsed))
        ) {
          throw new Error(
            `"${name}" must be ${type === "integer" ? "an integer" : "a number"}`
          );
        }
        return [name, parsed];
      }
      if (type === "boolean") {
        if (value !== "true" && value !== "false") {
          throw new Error(`"${name}" must be true or false`);
        }
        return [name, value === "true"];
      }
      return [name, value];
    })
  );
}

function decodeBase64Utf8(blob: string): string {
  try {
    const bytes = Uint8Array.from(atob(blob), (char) => char.charCodeAt(0));
    return new TextDecoder("utf-8", { fatal: true }).decode(bytes);
  } catch {
    throw new Error("MCP UI resource blob is not valid base64 UTF-8");
  }
}

/** Validate a `resources/read` answer for an app's HTML and read its UI metadata. */
export function uiResourceFromReadResult(
  result: ReadResourceResult,
  requestedUri: string
): McpAppUiResource {
  if (result.contents.length !== 1) {
    throw new Error("MCP UI resource must contain exactly one content item");
  }
  const [content] = result.contents;
  if (content.mimeType !== RESOURCE_MIME_TYPE) {
    throw new Error(
      `MCP UI resource must use MIME type "${RESOURCE_MIME_TYPE}"; received "${content.mimeType}"`
    );
  }
  const html =
    "blob" in content && typeof content.blob === "string"
      ? decodeBase64Utf8(content.blob)
      : "text" in content && typeof content.text === "string"
        ? content.text
        : null;
  if (html === null) {
    throw new Error("MCP UI resource must provide text or a base64 blob");
  }

  const meta = McpUiResourceMetaSchema.safeParse(content._meta?.ui ?? {});
  if (!meta.success) {
    throw new Error(
      `MCP UI resource metadata is invalid: ${meta.error.message}`
    );
  }
  return {
    uri: content.uri || requestedUri,
    html,
    csp: meta.data.csp,
    permissions: meta.data.permissions,
    prefersBorder: meta.data.prefersBorder,
  };
}
