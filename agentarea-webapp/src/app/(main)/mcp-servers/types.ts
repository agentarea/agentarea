import { components } from "@/api/schema";

/**
 * Shared types for MCP servers, instances, and OpenAPI connections
 * Based on API schema types
 */

export type MCPServerResponse = components["schemas"]["MCPServerResponse"];
export type MCPServerInstanceResponse =
  components["schemas"]["MCPServerInstanceResponse"];

/**
 * Extended MCP Server type with optional fields for UI
 */
export interface MCPServer extends MCPServerResponse {
  endpoint_url?: string;
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
  available_tools: Array<{ name: string; description: string; inputSchema?: any }>;
  custom_headers?: Array<{ name: string; secret: boolean; value: string | null }> | null;
  status: string;
  created_at: string;
  updated_at: string;
}

/**
 * Compound MCP type — virtual MCP grouping multiple instances
 */
export interface CompoundMCP {
  id: string;
  name: string;
  description?: string | null;
  routing_mode: "parallel" | "fallback" | "conditional";
  endpoint_url?: string | null;
  created_at: string;
  updated_at: string;
}

/**
 * Compound MCP member — links a compound to an MCP instance
 */
export interface CompoundMCPMember {
  mcp_instance_id: string;
  order: number;
  config: Record<string, any>;
  namespace: string;
}

/**
 * Unified connection item for the combined list
 */
export type ConnectionType = "mcp" | "openapi" | "compound";

export interface UnifiedConnection {
  id: string;
  name: string;
  description?: string | null;
  type: ConnectionType;
  status: string;
  toolCount: number;
  original: MCPInstance | OpenAPIConnection | CompoundMCP;
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
export type HealthStatus = "healthy" | "unhealthy" | "starting" | "unknown";

