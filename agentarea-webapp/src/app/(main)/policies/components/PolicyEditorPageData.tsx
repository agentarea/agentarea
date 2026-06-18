import { notFound } from "next/navigation";
import ContentBlock from "@/components/ContentBlock/ContentBlock";
import EmptyState from "@/components/EmptyState";
import {
  listAgents,
  listMCPServerInstances,
  listMCPServers,
  listOpenAPIConnections,
  listPolicies,
} from "@/lib/api";
import { getAuthContext } from "@/lib/getAuthContext";
import type { McpInstance, McpServer } from "@/lib/mcp/resolveMcpRef";
import type { Policy } from "@/types/policies";
import PolicyEditor, { type PolicyEditorTarget } from "./PolicyEditor";

interface OpenAPIConnectionLike {
  id: string;
  name: string;
  available_tools?: Array<{
    name: string;
    description?: string | null;
    inputSchema?: unknown;
  }> | null;
}

interface AgentLike {
  id: string;
  name: string;
  icon?: string | null;
  color_token?: string | null;
  tools?: Array<{
    type?: string | null;
    name?: string | null;
    settings?: Record<string, unknown> | null;
  }> | null;
  tools_config?: {
    builtin_tools?: Array<Record<string, unknown>> | null;
    mcp_server_configs?: Array<Record<string, unknown>> | null;
    openapi_configs?: Array<Record<string, unknown>> | null;
  } | null;
}

interface PolicyEditorPageDataProps {
  policyId?: string;
}

export async function PolicyEditorPageData({
  policyId,
}: PolicyEditorPageDataProps) {
  let policies: Policy[] = [];
  let agents: AgentLike[] = [];
  let mcpInstances: McpInstance[] = [];
  let mcpServers: McpServer[] = [];
  let openapiConnections: OpenAPIConnectionLike[] = [];
  let policiesError: string | null = null;

  const [
    policiesRes,
    agentsRes,
    mcpInstancesRes,
    mcpServersRes,
    openapiConnectionsRes,
    authContext,
  ] = await Promise.all([
    listPolicies().catch((reason) => ({ data: null, error: reason })),
    listAgents().catch((reason) => ({ data: null, error: reason })),
    listMCPServerInstances().catch((reason) => ({ data: null, error: reason })),
    listMCPServers({ page_size: 100 }).catch((reason) => ({
      data: null,
      error: reason,
    })),
    listOpenAPIConnections().catch((reason) => ({
      data: null,
      error: reason,
    })),
    getAuthContext(),
  ]);

  if (policiesRes.error) {
    console.error("Failed to fetch policies:", policiesRes.error);
    policiesError = "Failed to load policies";
  } else {
    policies = ((policiesRes.data as Policy[] | null) ?? []) as Policy[];
  }

  if (agentsRes.error) {
    console.error("Failed to load agents for policy editor:", agentsRes.error);
  } else {
    agents = ((agentsRes.data as AgentLike[] | null) ?? []).map((agent) => ({
      id: agent.id,
      name: agent.name,
      icon: agent.icon,
      color_token: agent.color_token,
      tools: Array.isArray(agent.tools) ? agent.tools : null,
      tools_config:
        agent.tools_config && typeof agent.tools_config === "object"
          ? agent.tools_config
          : null,
    }));
  }

  if (mcpInstancesRes.error) {
    console.error(
      "Failed to load MCP instances for policy editor:",
      mcpInstancesRes.error
    );
  } else {
    mcpInstances = ((mcpInstancesRes.data as McpInstance[] | null) ??
      []) as McpInstance[];
  }

  if (mcpServersRes.error) {
    console.error(
      "Failed to load MCP servers for policy editor:",
      mcpServersRes.error
    );
  } else {
    const data = mcpServersRes.data as
      | McpServer[]
      | { items?: McpServer[] }
      | null;
    mcpServers = Array.isArray(data) ? data : (data?.items ?? []);
  }

  if (openapiConnectionsRes.error) {
    console.error(
      "Failed to load OpenAPI connections for policy editor:",
      openapiConnectionsRes.error
    );
  } else {
    openapiConnections = ((openapiConnectionsRes.data as
      | OpenAPIConnectionLike[]
      | null) ?? []) as OpenAPIConnectionLike[];
  }

  const target = resolveTarget({ policyId, policies });
  if (!target) notFound();

  const title = policyId ? "Edit policy rule" : "New policy rule";

  return (
    <ContentBlock
      header={{
        breadcrumb: [
          { label: "Policies", href: "/policies" },
          { label: title },
        ],
      }}
    >
      <div className="main-content">
        {policiesError && policyId ? (
          <EmptyState
            title="Couldn't load policy"
            description={policiesError}
            iconsType="audit"
          />
        ) : (
          <PolicyEditor
            target={target}
            agents={agents}
            mcpInstances={mcpInstances}
            mcpServers={mcpServers}
            openapiConnections={openapiConnections}
            workspaceId={authContext.workspaceId}
            currentUserId={authContext.userId}
          />
        )}
      </div>
    </ContentBlock>
  );
}

function resolveTarget({
  policyId,
  policies,
}: {
  policyId?: string;
  policies: Policy[];
}): PolicyEditorTarget | null {
  if (policyId) {
    const policy = policies.find((item) => item.id === policyId);
    return policy ? { mode: "edit", policy } : null;
  }

  return { mode: "create-workspace" };
}
