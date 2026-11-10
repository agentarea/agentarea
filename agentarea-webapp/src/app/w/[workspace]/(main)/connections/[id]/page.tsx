import type { McpServerInstanceResponse } from "@/api/client/types.gen";
import { getMCPServerInstance } from "@/lib/api";
import { requireApiData } from "@/lib/server-resource";
import { loadConsumers } from "./consumersData";
import { getInstanceCached, loadServerSpec } from "./instanceData";
import MCPInstanceOverview from "./MCPInstanceOverview";

interface Props {
  params: Promise<{ id: string }>;
}

export default async function MCPInstancePage({ params }: Props) {
  const { id } = await params;
  const instance = await getInstanceCached(id);

  const [serverSpec, consumerResult] = await Promise.all([
    loadServerSpec(instance),
    loadConsumers(instance.id),
  ]);

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
