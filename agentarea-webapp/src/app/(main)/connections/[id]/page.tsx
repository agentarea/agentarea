import type { Metadata } from "next";
import type { McpServerInstanceResponse } from "@/api/client/types.gen";
import { getTranslations } from "next-intl/server";
import ContentBlock from "@/components/ContentBlock";
import { getMCPServer, getMCPServerInstance } from "@/lib/api";
import { requireApiData } from "@/lib/server-resource";
import MCPInstanceHeaderControls from "./HeaderControls";
import MCPInstanceDetail from "./MCPInstanceDetail";

interface Props {
  params: Promise<{ id: string }>;
}

export async function generateMetadata({ params }: Props): Promise<Metadata> {
  const { id } = await params;
  const instance = requireApiData(
    await getMCPServerInstance(id),
    "MCP instance"
  );
  return { title: instance?.name ?? "MCP Instance" };
}

export default async function MCPInstancePage({ params }: Props) {
  const { id } = await params;
  const t = await getTranslations("MCPServersPage");

  const instance = requireApiData(
    await getMCPServerInstance(id),
    "MCP instance"
  );

  const serverSpec = instance.server_spec_id
    ? requireApiData(await getMCPServer(instance.server_spec_id), "MCP server")
    : null;

  // Resolve bundle member names
  const memberNames: Record<string, string> = {};
  const jsonSpec = instance.json_spec;
  if (jsonSpec?.type === "bundle" && Array.isArray(jsonSpec.members)) {
    const results = await Promise.all(
      jsonSpec.members.map((memberId: string) => getMCPServerInstance(memberId))
    );
    for (let i = 0; i < jsonSpec.members.length; i++) {
      const memberId = jsonSpec.members[i];
      const memberData = requireApiData<McpServerInstanceResponse>(
        results[i],
        `MCP bundle member ${memberId}`
      );
      memberNames[memberId] = memberData?.name ?? memberId;
    }
  }

  return (
    <ContentBlock
      header={{
        breadcrumb: [
          { label: t("title"), href: "/connections" },
          { label: instance.name },
        ],
        controls: (
          <MCPInstanceHeaderControls
            instanceId={instance.id}
            instanceName={instance.name}
            instanceType={instance.json_spec?.type as string | undefined}
            hasAuthConfig={!!instance.auth_config_id}
          />
        ),
      }}
      className="p-0 overflow-hidden"
    >
      <MCPInstanceDetail
        instance={instance}
        serverSpec={serverSpec}
        memberNames={memberNames}
      />
    </ContentBlock>
  );
}
