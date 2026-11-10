import { notFound } from "next/navigation";
import { setMCPServerInstanceSharingAction } from "@/lib/server-actions";
import ConnectionAccess from "../../components/ConnectionAccess";
import { getInstanceCached } from "../instanceData";

interface Props {
  params: Promise<{ id: string }>;
}

export default async function MCPInstanceAccessPage({ params }: Props) {
  const { id } = await params;
  const instance = await getInstanceCached(id);
  // A managed connection's access is its manager's; it has no Access tab.
  if (instance.managed_by) notFound();
  return (
    <ConnectionAccess
      personal={instance.personal ?? false}
      isOwner={instance.is_owner ?? false}
      onShare={setMCPServerInstanceSharingAction.bind(null, instance.id)}
    />
  );
}
