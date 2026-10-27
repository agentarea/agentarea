import { loadConsumers } from "../consumersData";
import { getInstanceCached } from "../instanceData";
import { loadToolPolicies } from "../toolPolicyData";
import InstanceToolsView from "./InstanceToolsView";

interface Props {
  params: Promise<{ id: string }>;
}

export default async function ConnectionToolsPage({ params }: Props) {
  const { id } = await params;
  const [instance, { consumers, error }, toolPolicies] = await Promise.all([
    getInstanceCached(id),
    loadConsumers(id),
    loadToolPolicies(id),
  ]);

  return (
    <InstanceToolsView
      instance={instance}
      consumers={consumers}
      consumersError={error}
      toolPolicies={toolPolicies}
    />
  );
}
