import type { Metadata } from "next";
import { notFound } from "next/navigation";
import ContentBlock from "@/components/ContentBlock";
import { getMCPServerInstance, getMCPServer } from "@/lib/api";
import MCPInstanceDetail from "./MCPInstanceDetail";

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
          { label: "MCP Servers", href: "/mcp-servers" },
          { label: instance.name },
        ],
      }}
      className="p-0"
    >
      <MCPInstanceDetail instance={instance as any} serverSpec={serverSpec as any} />
    </ContentBlock>
  );
}
