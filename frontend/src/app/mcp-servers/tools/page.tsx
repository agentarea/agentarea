import { listMCPServerInstances } from "@/lib/api";
import { MyMCPsSection } from "../components/MyMCPsSection";
import ClientWrapper from "../ClientWrapper";
import { Button } from "@/components/ui/button";
import Link from "next/link";
import { Plus, ArrowLeft } from "lucide-react";
import ContentBlock from "@/components/ContentBlock";
import { getTranslations } from "next-intl/server";

export default async function MCPToolsPage() {
  const mcpInstances = await listMCPServerInstances();
  const mcpInstanceList = mcpInstances.data || [];
  const t = await getTranslations("MCPServersPage");

  return (
    <ContentBlock 
    header={{
      breadcrumb: [
        {label: t("title"), href: "/mcp-servers"},
        {label: t("tools.title")},
      ],
      description: t("tools.description"),
      controls: (
        <div className="flex flex-col items-center lg:items-end gap-2">
        <div className="flex items-center gap-2 text-xs text-muted-foreground">
          <div className="h-1.5 w-1.5 bg-green-500 rounded-full animate-pulse"></div>
          {mcpInstanceList.length} Active Tools
        </div>
        <div className="flex gap-2">
          <Button variant="outline" size="sm" asChild>
            <Link href="/mcp-servers/marketplace" className="flex items-center gap-2">
              <Plus className="h-4 w-4" />
              Browse Marketplace
            </Link>
          </Button>
          <Button size="sm" asChild>
            <Link href="/mcp-servers/add" className="flex items-center gap-2">
              <Plus className="h-4 w-4" />
              Add Custom Tool
            </Link>
          </Button>
        </div>
      </div>
      )
    }}>
      <ClientWrapper>
            {/* My MCPs Section */}
            <div id="my-mcps" className="mb-6">
              <MyMCPsSection mcpInstances={mcpInstanceList} />
            </div>

            {/* Footer */}
            <div className="mt-8 pt-4 border-t border-slate-200 dark:border-slate-700">
              <div className="text-center text-xs text-muted-foreground">
                <p>Having issues with your MCP tools? Check the status indicators and configuration settings.</p>
              </div>
            </div>
      </ClientWrapper>
    </ContentBlock>
  );
}