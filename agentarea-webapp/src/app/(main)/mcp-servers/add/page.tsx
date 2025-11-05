import { getTranslations } from "next-intl/server";
import ContentBlock from "@/components/ContentBlock/ContentBlock";
import {
  Card,
  CardDescription,
  CardHeader,
  CardTitle,
} from "@/components/ui/card";
import { AddMCPServerForm } from "./form";

export default async function AddMCPServerPage() {
  const t = await getTranslations("MCPServersPage");
  const commonT = await getTranslations("Common");

  return (
    <ContentBlock
      header={{
        breadcrumb: [
          { label: t("title"), href: "/mcp-servers" },
          { label: t("newServer.title") },
        ],
        description: t("newServer.description"),
        backLink: {
          label: "Back to MCP Servers",
          href: "/mcp-servers",
        },
      }}
    >
      <div className="mx-auto max-w-2xl">
        <Card>
          <CardHeader>
            <CardTitle>Add MCP Server</CardTitle>
            <CardDescription>
              Connect an MCP server to your workspace
            </CardDescription>
          </CardHeader>
          <AddMCPServerForm />
        </Card>
      </div>
    </ContentBlock>
  );
}
