import type { Metadata } from "next";
import { getTranslations } from "next-intl/server";
import { notFound } from "next/navigation";
import {
  getMCPServer,
  getMCPServerInstance,
  getToolCallApproval,
  resolvePrincipals,
} from "@/lib/api";
import { mcpIdentity, type EntityIdentity } from "@/lib/entity-identity";
import { optionalApiData, requireApiData } from "@/lib/server-resource";
import { getWorkspaces } from "@/lib/workspace-context";
import ApproveToolCall from "./ApproveToolCall";

interface Props {
  params: Promise<{ workspace: string; approvalId: string }>;
}

export async function generateMetadata({ params }: Props): Promise<Metadata> {
  const { approvalId } = await params;
  const t = await getTranslations("Approvals.link");
  const approval = requireApiData(
    await getToolCallApproval(approvalId),
    "Tool call approval"
  );
  return { title: t("metaTitle", { tool: approval.tool }) };
}

/** The connection's mark; a platform tool belongs to no connection. */
async function connectorIdentity(
  instanceId: string | null
): Promise<EntityIdentity> {
  if (!instanceId) return { kind: "tool", sources: [] };
  const instance = optionalApiData(
    await getMCPServerInstance(instanceId),
    `MCP instance ${instanceId}`
  );
  if (!instance) return { kind: "mcp", sources: [] };
  const serverSpec = optionalApiData(
    await getMCPServer(instance.server_spec_id),
    `MCP server ${instance.server_spec_id}`
  );
  const endpointUrl =
    (typeof instance.json_spec.endpoint_url === "string" &&
      instance.json_spec.endpoint_url) ||
    serverSpec?.remote_url;
  return mcpIdentity(instance, serverSpec, endpointUrl);
}

/**
 * Where an approval link lands: a client asked to run a tool the workspace
 * policy holds for approval. The person sees the exact call and decides; the
 * client's retry with the same arguments then runs it once.
 */
export default async function ApprovePage({ params }: Props) {
  const { workspace, approvalId } = await params;
  const approval = requireApiData(
    await getToolCallApproval(approvalId),
    "Tool call approval"
  );
  const [workspaces, principals, identity] = await Promise.all([
    getWorkspaces(),
    resolvePrincipals([approval.requested_by]),
    connectorIdentity(approval.mcp_instance_id),
  ]);
  const current = workspaces.find((candidate) => candidate.slug === workspace);
  if (!current) notFound();
  if (principals.error) {
    console.error("Failed to resolve who asked for approval", principals.error);
  }
  const requester = principals.data?.[0];
  const requesterName =
    requester?.display_name?.trim() ||
    requester?.email?.trim() ||
    approval.requested_by;

  return (
    <ApproveToolCall
      approval={approval}
      requesterName={requesterName}
      workspaceName={current.name}
      identity={identity}
    />
  );
}
