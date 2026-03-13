import type { Metadata } from "next";
import { getTranslations } from "next-intl/server";
import ContentBlock from "@/components/ContentBlock/ContentBlock";
import { Button } from "@/components/ui/button";
import { listMCPServers } from "@/lib/api";
import CreateMCPInstanceClient from "./CreateMCPInstanceClient";
import type { MCPServer } from "../../types";

export const metadata: Metadata = {
  title: "Create MCP Instance",
};

export default async function CreateMCPInstancePage({
  params,
}: {
  params: Promise<{ id: string }>;
}) {
  const { id } = await params;
  const t = await getTranslations("MCPServersPage");

  const serversResponse = await listMCPServers();
  const mcpServers = (serversResponse.data || []) as MCPServer[];
  const mcpServer = mcpServers.find((s) => String(s.id) === String(id));

  return (
    <ContentBlock
      header={{
        breadcrumb: [
          { label: t("title"), href: "/mcp-servers" },
          { label: mcpServer ? `Create ${mcpServer.name} instance` : "Create instance" },
        ],
        description: mcpServer?.description,
        backLink: {
          label: "Back to MCP Servers",
          href: "/mcp-servers",
        },
        controls: (
          <div className="flex items-center gap-2 py-1">
            <Button size="xs" type="submit" form="mcp-instance-form">
              Create Instance
            </Button>
          </div>
        ),
      }}
    >
      {!mcpServer ? (
        <div className="py-6">
          <div className="rounded-lg border border-destructive/20 bg-destructive/5 p-4 text-sm text-destructive">
            {serversResponse.error
              ? (serversResponse.error as any)?.detail?.[0]?.msg ||
                (serversResponse.error as any)?.detail ||
                (serversResponse.error as any)?.message ||
                "Failed to load MCP servers"
              : "MCP server spec not found"}{" "}
            (id: {id})
          </div>
        </div>
      ) : (
        <CreateMCPInstanceClient server={mcpServer} />
      )}
    </ContentBlock>
  );
}
