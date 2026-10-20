import { getOpenAPIConnectionCached } from "./connectionData";
import OpenAPIConnectionOverview from "./OpenAPIConnectionOverview";

interface Props {
  params: Promise<{ id: string }>;
}

export default async function OpenAPIConnectionPage({ params }: Props) {
  const { id } = await params;
  const connection = await getOpenAPIConnectionCached(id);
  return <OpenAPIConnectionOverview connection={connection} />;
}
