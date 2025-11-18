import { components } from "@/api/schema";

/**
 * Shared types for MCP servers and instances
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

