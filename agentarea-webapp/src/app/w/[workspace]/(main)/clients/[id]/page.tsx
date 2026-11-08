import { getClient, listRunnerKeys } from "@/lib/api";
import { RUNNER_KINDS } from "@/lib/runner-kinds";
import { optionalApiData, requireApiData } from "@/lib/server-resource";
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
  const keys = optionalApiData(await listRunnerKeys(id), "runner keys");
  return (
    <ClientDetail
      initialClient={client}
      runner={<ClientRunner client={client} keys={keys} />}
    />
  );
}
