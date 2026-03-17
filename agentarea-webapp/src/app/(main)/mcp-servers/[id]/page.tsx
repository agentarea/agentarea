import type { Metadata } from "next";
import { notFound } from "next/navigation";
import { getTranslations } from "next-intl/server";
import ContentBlock from "@/components/ContentBlock";
import { getMCPServerInstance, getMCPServer } from "@/lib/api";
import MCPInstanceDetail from "./MCPInstanceDetail";
import MCPInstanceHeaderControls from "./HeaderControls";

interface Props {
  params: Promise<{ id: string }>;
}

export async function generateMetadata({ params }: Props): Promise<Metadata> {
  const { id } = await params;
  const { data: instance } = await getMCPServerInstance(id);
  return { title: instance?.name ?? "MCP Instance" };
}

export default async function MCPInstancePage({ params }: Props) {
  const { id } = await params;
  const t = await getTranslations("MCPServersPage");

  const { data: instance } = await getMCPServerInstance(id);
  if (!instance) notFound();

  const serverSpec =
    instance.server_spec_id
      ? (await getMCPServer(instance.server_spec_id)).data ?? null
      : null;

  return (
    <ContentBlock
      header={{
        breadcrumb: [
          { label: t("title"), href: "/mcp-servers" },
          { label: instance.name },
        ],
        controls: (
          <MCPInstanceHeaderControls
            instanceId={instance.id}
            instanceName={instance.name}
            status={instance.status}
          />
        ),
      }}
      className="p-0 overflow-hidden"
    >
      <MCPInstanceDetail
        instance={instance as any}
        serverSpec={serverSpec as any}
      />
    </ContentBlock>
  );
}
