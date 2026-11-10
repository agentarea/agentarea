import { notFound } from "next/navigation";
import { setOpenAPIConnectionSharingAction } from "@/lib/server-actions";
import ConnectionAccess from "../../../components/ConnectionAccess";
import { getOpenAPIConnectionCached } from "../connectionData";

interface Props {
  params: Promise<{ id: string }>;
}

export default async function OpenAPIConnectionAccessPage({ params }: Props) {
  const { id } = await params;
  const connection = await getOpenAPIConnectionCached(id);
  // A managed connection's access is its manager's; it has no Access tab.
  if (connection.managed_by) notFound();
  return (
    <ConnectionAccess
      personal={connection.personal ?? false}
      isOwner={connection.is_owner ?? false}
      onShare={setOpenAPIConnectionSharingAction.bind(null, connection.id)}
    />
  );
}
