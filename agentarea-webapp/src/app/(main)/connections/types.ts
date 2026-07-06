import type { McpServerInstanceResponse, McpServerResponse } from "@/api/client/types.gen";

/**
 * Shared types for MCP servers, instances, and OpenAPI connections
 * Based on API schema types
 */

export type MCPServerResponse = McpServerResponse;
export type MCPServerInstanceResponse =
  McpServerInstanceResponse;

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

/**
 * OpenAPI Connection type (not yet in generated schema)
 */
export interface OpenAPIConnection {
  id: string;
  name: string;
  base_url: string;
  description?: string | null;
  spec_url?: string | null;
  auth_config_id?: string | null;
  available_tools: Array<{ name: string; description: string; inputSchema?: Record<string, unknown> }>;
  custom_headers?: Array<{ name: string; secret: boolean; value: string | null }> | null;
  status: string;
  created_at: string;
  updated_at: string;
}

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

/**
 * Health check result for MCP instances
 */
export interface HealthCheck {
  service_name: string;
  slug: string;
  url: string;
  healthy: boolean;
  http_reachable: boolean;
  response_time_ms: number;
  error?: string;
}

/**
 * Health status type
 */
export type HealthStatus = "healthy" | "unhealthy" | "starting" | "connected" | "unknown";

