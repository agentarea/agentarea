import { bindsEgressExit } from "../../egress-exit";
import { loadEgressExitChoices } from "../../egressExitsData";
import { getInstanceCached, loadServerSpec } from "../instanceData";
import MCPInstanceSettings from "./MCPInstanceSettings";

interface Props {
  params: Promise<{ id: string }>;
}

export default async function MCPInstanceSettingsPage({ params }: Props) {
  const { id } = await params;
  const instance = await getInstanceCached(id);

  const [serverSpec, egressExits] = await Promise.all([
    instance.transport === "url" ? loadServerSpec(instance) : null,
    bindsEgressExit(instance.transport) ? loadEgressExitChoices() : null,
  ]);

  return (
    <MCPInstanceSettings
      instance={instance}
      serverSpec={serverSpec}
      egressExits={egressExits}
    />
  );
}
