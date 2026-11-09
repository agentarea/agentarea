import { listAgents, listRunnerKeys } from "@/lib/api";
import { RUNNER_KINDS } from "@/lib/runner-kinds";
import { optionalApiData, requireApiData } from "@/lib/server-resource";
import { getClientCached } from "./clientData";
import ClientOverview from "./ClientOverview";

export default async function ClientPage({
  params,
}: {
  params: Promise<{ id: string }>;
}) {
  const { id } = await params;
  const client = await getClientCached(id);
  if (!RUNNER_KINDS.includes(client.kind)) {
    return <ClientOverview client={client} runner={null} />;
  }
  // Only those who may edit the client see its runner's keys.
  const [keys, agents] = await Promise.all([
    listRunnerKeys(id).then((result) => optionalApiData(result, "runner keys")),
    listAgents().then((result) => requireApiData(result, "agents")),
  ]);
  return (
    <ClientOverview
      client={client}
      runner={{
        keyCount: keys?.length ?? null,
        agents: agents.filter((agent) => agent.client_id === id),
      }}
    />
  );
}
