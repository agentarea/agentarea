import type { McpServerInstanceResponse } from "@/api/client/types.gen";
import { getMCPServer, getMCPServerInstance } from "@/lib/api";
import { optionalApiData, requireApiData } from "@/lib/server-resource";
import { loadConsumers } from "./consumersData";
import { getInstanceCached } from "./instanceData";
import MCPInstanceOverview from "./MCPInstanceOverview";

interface Props {
  params: Promise<{ id: string }>;
}

export default async function MCPInstancePage({ params }: Props) {
  const { id } = await params;
  const instance = await getInstanceCached(id);

  const [serverSpecResult, consumerResult] = await Promise.all([
    instance.server_spec_id ? getMCPServer(instance.server_spec_id) : null,
    loadConsumers(instance.id),
  ]);
  const serverSpec =
    serverSpecResult && instance.server_spec_id
      ? optionalApiData(
          serverSpecResult,
          `MCP server ${instance.server_spec_id}`
        )
      : null;

  // Resolve bundle member names
  const memberNames: Record<string, string> = {};
  const jsonSpec = instance.json_spec;
  if (instance.transport === "bundle" && Array.isArray(jsonSpec.members)) {
    const results = await Promise.all(
      jsonSpec.members.map((memberId: string) => getMCPServerInstance(memberId))
    );
    for (let i = 0; i < jsonSpec.members.length; i++) {
      const memberId = jsonSpec.members[i];
      const memberData = requireApiData<McpServerInstanceResponse>(
        results[i],
        `MCP bundle member ${memberId}`
      );
      memberNames[memberId] = memberData?.name ?? memberId;
    }
  }

  return (
    <MCPInstanceOverview
      instance={instance}
      serverSpec={serverSpec}
      memberNames={memberNames}
      consumers={consumerResult.consumers}
      consumersError={consumerResult.error}
    />
  );
}
