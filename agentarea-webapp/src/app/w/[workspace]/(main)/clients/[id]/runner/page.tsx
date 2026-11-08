import { notFound } from "next/navigation";
import { listRunnerKeys } from "@/lib/api";
import { RUNNER_KINDS } from "@/lib/runner-kinds";
import { optionalApiData } from "@/lib/server-resource";
import { getClientCached } from "../clientData";
import { ClientRunner } from "./ClientRunner";

export default async function ClientRunnerPage({
  params,
}: {
  params: Promise<{ id: string }>;
}) {
  const { id } = await params;
  const client = await getClientCached(id);
  if (!RUNNER_KINDS.includes(client.kind)) notFound();
  // Only those who may edit the client see and manage its runner's keys.
  const keys = optionalApiData(await listRunnerKeys(id), "runner keys");
  return <ClientRunner client={client} keys={keys} />;
}
