import type { Metadata } from "next";
import { getTranslations } from "next-intl/server";
import ContentBlock from "@/components/ContentBlock";
import ConnectionDetailTabs from "../../components/ConnectionDetailTabs";
import { getOpenAPIConnectionCached } from "./connectionData";
import OpenAPIConnectionHeaderControls from "./HeaderControls";

interface Props {
  params: Promise<{ id: string }>;
  children: React.ReactNode;
}

export async function generateMetadata({ params }: Props): Promise<Metadata> {
  const { id } = await params;
  const connection = await getOpenAPIConnectionCached(id);
  return { title: connection.name };
}

export default async function OpenAPIConnectionLayout({ params, children }: Props) {
  const { id } = await params;
  const t = await getTranslations("MCPServersPage");
  const connection = await getOpenAPIConnectionCached(id);

  return (
    <ContentBlock
      header={{
        breadcrumb: [
          { label: t("title"), href: "/connections" },
          { label: connection.name, href: `/connections/openapi/${id}` },
        ],
        controls: (
          <OpenAPIConnectionHeaderControls
            connectionId={connection.id}
            connectionName={connection.name}
          />
        ),
      }}
      className="p-0"
      subheader={
        // OpenAPI connection changes are not audited, so no Activity tab.
        <ConnectionDetailTabs
          basePath={`/connections/openapi/${id}`}
          toolCount={connection.available_tools.length}
          without={["activity"]}
        />
      }
    >
      {children}
    </ContentBlock>
  );
}
