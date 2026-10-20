import { loadConsumers } from "../consumersData";
import { getInstanceCached } from "../instanceData";
import InstanceToolsView from "./InstanceToolsView";

interface Props {
  params: Promise<{ id: string }>;
}

export default async function ConnectionToolsPage({ params }: Props) {
  const { id } = await params;
  const [instance, { consumers, error }] = await Promise.all([
    getInstanceCached(id),
    loadConsumers(id),
  ]);

  return (
    <InstanceToolsView
      instance={instance}
      consumers={consumers}
      consumersError={error}
    />
  );
}
