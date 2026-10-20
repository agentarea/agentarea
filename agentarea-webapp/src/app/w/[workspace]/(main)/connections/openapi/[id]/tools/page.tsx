import { getOpenAPIConnectionCached } from "../connectionData";
import OpenAPIToolsView from "./OpenAPIToolsView";

interface Props {
  params: Promise<{ id: string }>;
}

export default async function OpenAPIConnectionToolsPage({ params }: Props) {
  const { id } = await params;
  const connection = await getOpenAPIConnectionCached(id);
  return <OpenAPIToolsView connection={connection} />;
}
