import { getOpenAPIConnectionCached } from "../connectionData";
import OpenAPIConnectionSettings from "./OpenAPIConnectionSettings";

interface Props {
  params: Promise<{ id: string }>;
}

export default async function OpenAPIConnectionSettingsPage({ params }: Props) {
  const { id } = await params;
  const connection = await getOpenAPIConnectionCached(id);
  return <OpenAPIConnectionSettings connection={connection} />;
}
