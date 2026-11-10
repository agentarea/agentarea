import type { Metadata } from "next";
import { getTranslations } from "next-intl/server";
import ContentBlock from "@/components/ContentBlock";
import { getClientCached } from "./clientData";
import ClientDetailTabs from "./ClientDetailTabs";
import ClientHeaderControls from "./ClientHeaderControls";

interface Props {
  params: Promise<{ id: string }>;
  children: React.ReactNode;
}

export async function generateMetadata({ params }: Props): Promise<Metadata> {
  const { id } = await params;
  const client = await getClientCached(id);
  return { title: client.name };
}

export default async function ClientLayout({ params, children }: Props) {
  const { id } = await params;
  const t = await getTranslations("ClientsPage");
  const client = await getClientCached(id);
  const toolCount =
    (client.mcp_instances?.length ?? 0) +
    (client.platform_toolsets?.length ?? 0) +
    (client.skills?.length ?? 0);

  return (
    <ContentBlock
      header={{
        breadcrumb: [
          { label: t("title"), href: "/clients" },
          { label: client.name, href: `/clients/${id}` },
        ],
        controls: <ClientHeaderControls client={client} />,
      }}
      className="p-0"
      subheader={
        <ClientDetailTabs
          basePath={`/clients/${id}`}
          toolCount={toolCount}
          withRunner={client.has_runner ?? false}
        />
      }
    >
      {children}
    </ContentBlock>
  );
}
