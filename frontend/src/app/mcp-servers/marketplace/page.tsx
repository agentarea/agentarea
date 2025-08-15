import { listMCPServers } from "@/lib/api";
import { MCPSpecsSection } from "../components/MCPSpecsSection";
import { ActionCards } from "../components/ActionCards";
import ClientWrapper from "../ClientWrapper";
import ContentBlock from "@/components/ContentBlock";
import { getTranslations } from "next-intl/server";

export default async function MCPMarketplacePage({
  searchParams,
}: {
  searchParams: Promise<{ [key: string]: string | string[] | undefined }>
}) {
  const t = await getTranslations("MCPServersPage");
  const [mcpServers, resolvedSearchParams] = await Promise.all([
    listMCPServers(),
    searchParams,
  ]);

  const mcpList = mcpServers.data || [];

  return (
    <ContentBlock 
    header={{
      breadcrumb: [
        {label: t("title"), href: "/mcp-servers"},
        {label: t("marketplace.title")},
      ],
      description: t("marketplace.description"),
      controls: (
        <div className="flex flex-col items-center lg:items-end gap-2">
          <div className="flex items-center gap-2 text-xs text-muted-foreground">
            <div className="h-1.5 w-1.5 bg-blue-500 rounded-full"></div>
            {mcpList.length} Available Providers
          </div>
        </div>
      )
    }}>
      <ClientWrapper>
        {/* Quick Actions */}
        <div className="mb-6">
          <ActionCards />
        </div>

        {/* Browse MCP Specifications Section */}
        <div id="specs-section" className="mb-6">
          <MCPSpecsSection mcpServers={mcpList} searchParams={resolvedSearchParams} />
        </div>

        {/* Footer */}
        <div className="mt-8 pt-4 border-t border-slate-200 dark:border-slate-700">
          <div className="text-center text-xs text-muted-foreground">
            <p>Need help setting up MCP servers? Check out our documentation or join the community.</p>
          </div>
        </div>
      </ClientWrapper>
    </ContentBlock>
  );
}