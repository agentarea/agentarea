import type { Metadata } from "next";
import { getTranslations } from "next-intl/server";
import ContentBlock from "@/components/ContentBlock";
import { getMCPInstanceToolCount } from "../utils";
import ConnectionDetailTabs from "./ConnectionDetailTabs";
import MCPInstanceHeaderControls from "./HeaderControls";
import { getInstanceCached } from "./instanceData";

interface Props {
  params: Promise<{ id: string }>;
  children: React.ReactNode;
}

export async function generateMetadata({ params }: Props): Promise<Metadata> {
  const { id } = await params;
  const instance = await getInstanceCached(id);
  return { title: instance?.name ?? "MCP Instance" };
}

export default async function ConnectionLayout({ params, children }: Props) {
  const { id } = await params;
  const t = await getTranslations("MCPServersPage");
  const instance = await getInstanceCached(id);

  return (
    <ContentBlock
      header={{
        breadcrumb: [
          { label: t("title"), href: "/connections" },
          { label: instance.name, href: `/connections/${id}` },
        ],
        controls: (
          <MCPInstanceHeaderControls
            instanceId={instance.id}
            instanceName={instance.name}
          />
        ),
      }}
      className="p-0"
      subheader={
        <ConnectionDetailTabs
          instanceId={id}
          toolCount={getMCPInstanceToolCount(instance)}
        />
      }
    >
      {children}
    </ContentBlock>
  );
}
