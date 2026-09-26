import type {
  McpServerInstanceResponse,
  McpServerResponse,
  OpenApiConnectionResponse,
} from "@/api/client/types.gen";

/**
 * Shared types for MCP servers, instances, and OpenAPI connections
 * Based on API schema types
 */

export type MCPServerResponse = McpServerResponse;
export type MCPServerInstanceResponse = McpServerInstanceResponse;

/**
 * Extended MCP Server type with optional fields for UI
 */
export interface MCPServer extends MCPServerResponse {
  endpoint_url?: string;
  remote_url?: string | null;
}

/**
 * Extended MCP Instance type with optional fields for UI
 */
export interface MCPInstance extends MCPServerInstanceResponse {
  endpoint_url?: string;
}

export type OpenAPIConnection = OpenApiConnectionResponse;

/**
 * Unified connection item for the combined list
 */
export type ConnectionType = "mcp" | "openapi";

export interface UnifiedConnection {
  id: string;
  name: string;
  description?: string | null;
  type: ConnectionType;
  verificationStatus?: string;
  toolCount: number;
  original: MCPInstance | OpenAPIConnection;
}
