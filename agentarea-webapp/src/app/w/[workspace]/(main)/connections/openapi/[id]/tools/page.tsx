import { loadToolPolicies } from "../../../toolPolicyData";
import { getOpenAPIConnectionCached } from "../connectionData";
import OpenAPIToolsView from "./OpenAPIToolsView";

interface Props {
  params: Promise<{ id: string }>;
}

export default async function OpenAPIConnectionToolsPage({ params }: Props) {
  const { id } = await params;
  const [connection, toolPolicies] = await Promise.all([
    getOpenAPIConnectionCached(id),
    loadToolPolicies({ kind: "openapi", id }),
  ]);
  return (
    <OpenAPIToolsView connection={connection} toolPolicies={toolPolicies} />
  );
}
