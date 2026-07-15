import type { Metadata } from "next";
import { getTranslations } from "next-intl/server";
import ContentBlock from "@/components/ContentBlock/ContentBlock";
import { getMCPServer } from "@/lib/api";
import CreateMCPInstanceClient from "./CreateMCPInstanceClient";
import type { MCPServer } from "../../types";
import MCPCreateHeaderControls from "./HeaderControls";

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

  const { data: mcpServerData, error: serverError } = await getMCPServer(id);
  const mcpServer = mcpServerData as MCPServer | null;

  const serverErr = serverError as { detail?: Array<{ msg?: string }> | string; message?: string } | null;
  const serverErrorText = serverErr
    ? (Array.isArray(serverErr.detail) ? serverErr.detail[0]?.msg : serverErr.detail) ||
      serverErr.message ||
      t("createInstance.errors.loadServersFailed")
    : t("createInstance.errors.specNotFound");

  return (
    <ContentBlock
      header={{
        breadcrumb: [
          { label: t("title"), href: "/connections" },
          {
            label: mcpServer
              ? t("createInstance.breadcrumbWithName", { serverName: mcpServer.name })
              : t("createInstance.breadcrumb"),
          },
        ],
        description: mcpServer?.description,
        backLink: {
          label: t("createInstance.back"),
          href: "/connections",
        },
        controls: <MCPCreateHeaderControls />,
      }}
    >
      {!mcpServer ? (
        <div className="py-6">
          <div className="rounded-lg border border-destructive/20 bg-destructive/5 p-4 text-sm text-destructive">
            {serverErrorText}{" "}
            (id: {id})
          </div>
        </div>
      ) : (
        <CreateMCPInstanceClient server={mcpServer} />
      )}
    </ContentBlock>
  );
}
