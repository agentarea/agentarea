import { getTranslations } from "next-intl/server";
import { notFound } from "next/navigation";
import { AdminOnlyState } from "@/components/AdminOnlyState";
import ContentBlock from "@/components/ContentBlock/ContentBlock";
import RetryEmptyState from "@/components/EmptyState/RetryEmptyState";
import {
  listAgents,
  listMCPServerInstances,
  listMCPServers,
  listOpenAPIConnections,
  listPolicies,
  listWorkspaceMembers,
  type WorkspaceMember,
} from "@/lib/api";
import { apiErrorMessage } from "@/lib/api-errors";
import { getAuthContext } from "@/lib/getAuthContext";
import type { McpInstance, McpServer } from "@/lib/mcp/resolveMcpRef";
import { getViewerCapabilities } from "@/lib/workspace-context";
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

interface MemberLike {
  user_id: string;
  email?: string | null;
  display_name?: string | null;
}

interface AgentLike {
  id: string;
  name: string;
  icon?: string | null;

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
  const title = policyId ? "Edit policy rule" : "New policy rule";
  const header = {
    breadcrumb: [{ label: "Policies", href: "/policies" }, { label: title }],
  };

  const { canAdminister } = await getViewerCapabilities();
  if (!canAdminister) {
    return (
      <ContentBlock header={header}>
        <div className="main-content">
          <AdminOnlyState what="policyEditor" />
        </div>
      </ContentBlock>
    );
  }

  let policies: Policy[] = [];
  let agents: AgentLike[] = [];
  let mcpInstances: McpInstance[] = [];
  let mcpServers: McpServer[] = [];
  let openapiConnections: OpenAPIConnectionLike[] = [];
  let members: MemberLike[] = [];
  const authContext = await getAuthContext();

  const [
    policiesRes,
    agentsRes,
    mcpInstancesRes,
    mcpServersRes,
    openapiConnectionsRes,
    membersRes,
  ] = await Promise.all([
    listPolicies().catch((reason) => ({
      data: null,
      error: reason,
      status: undefined,
    })),
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
    listWorkspaceMembers().catch((reason) => ({ data: null, error: reason })),
  ]);

  if (policiesRes.error) {
    console.error("Failed to fetch policies:", policiesRes.error);
    if (policyId) {
      const t = await getTranslations("PoliciesPage.editor");
      return (
        <ContentBlock header={header}>
          <div className="main-content">
            <RetryEmptyState
              title={t("loadFailedTitle")}
              description={apiErrorMessage(policiesRes, t("loadFailed"))}
              iconsType="audit"
            />
          </div>
        </ContentBlock>
      );
    }
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

  if (membersRes.error) {
    console.error(
      "Failed to load members for policy editor:",
      membersRes.error
    );
  } else {
    members = (
      ((membersRes.data as WorkspaceMember[] | null) ?? []) as WorkspaceMember[]
    ).map((member) => ({
      user_id: member.user_id,
      email: member.email,
      display_name: member.display_name,
    }));
  }

  if (
    authContext.userId &&
    !members.some((member) => member.user_id === authContext.userId)
  ) {
    members = [
      {
        user_id: authContext.userId,
        email: authContext.email,
        display_name:
          authContext.name || authContext.email || authContext.username || null,
      },
      ...members,
    ];
  }

  const target = resolveTarget({ policyId, policies });
  if (!target) notFound();

  return (
    <ContentBlock header={header}>
      <div className="main-content">
        <PolicyEditor
          target={target}
          agents={agents}
          mcpInstances={mcpInstances}
          mcpServers={mcpServers}
          openapiConnections={openapiConnections}
          members={members}
          workspaceId={authContext.workspaceId}
        />
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
