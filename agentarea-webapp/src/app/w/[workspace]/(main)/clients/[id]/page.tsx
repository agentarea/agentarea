import Divider from "@/components/ui/divider";
import { getClient, listAgents, listRunnerKeys } from "@/lib/api";
import { RUNNER_KINDS } from "@/lib/runner-kinds";
import { optionalApiData, requireApiData } from "@/lib/server-resource";
import { ClientAgents } from "./ClientAgents";
import ClientDetail from "./ClientDetail";
import { ClientRunner } from "./ClientRunner";

export default async function ClientPage({
  params,
}: {
  params: Promise<{ id: string }>;
}) {
  const { id } = await params;
  const client = requireApiData(await getClient(id), "harness");
  if (!RUNNER_KINDS.includes(client.kind)) {
    return <ClientDetail initialClient={client} runner={null} />;
  }
  // Only those who may edit the client see and manage its runner's keys.
  const [keys, agents] = await Promise.all([
    listRunnerKeys(id).then((result) => optionalApiData(result, "runner keys")),
    listAgents().then((result) => requireApiData(result, "agents")),
  ]);
  return (
    <ClientDetail
      initialClient={client}
      runner={
        <>
          <ClientRunner client={client} keys={keys} />
          <Divider />
          <ClientAgents
            agents={agents.filter((agent) => agent.client_id === id)}
          />
        </>
      }
    />
  );
}
