import { Suspense } from "react";
import { getTranslations } from "next-intl/server";
import { cookies } from "next/headers";
import Link from "next/link";
import { Plus } from "lucide-react";
import ContentBlock from "@/components/ContentBlock";
import { LoadingSpinner } from "@/components/LoadingSpinner";
import SearchInput from "@/components/SearchInput";
import { Button } from "@/components/ui/button";
import MCPHeaderTabs from "./components/MCPHeaderTabs";
import MCPServersContent from "./components/MCPServersContent";

export default async function MCPServersPage({
  searchParams,
}: {
  searchParams: Promise<{ [key: string]: string | string[] | undefined }>;
}) {
  const t = await getTranslations("MCPServersPage");
  const resolvedSearchParams = await searchParams;

  // Read tab from URL or fallback to cookie
  const cookieStore = await cookies();
  const cookieTab = cookieStore.get("tab_mcp-servers")?.value;
  const tab =
    typeof resolvedSearchParams.tab === "string"
      ? resolvedSearchParams.tab
      : cookieTab || "grid";
  const searchQuery =
    typeof resolvedSearchParams.search === "string"
      ? resolvedSearchParams.search
      : "";

  return (
    <ContentBlock
      header={{
        breadcrumb: [{ label: t("title") }],
        description: t("description"),
        controls: (
          <Link href="/mcp-servers/add">
            <Button
              className="shrink-0 gap-2"
              size="xs"
              data-test="new-mcp-button"
            >
              <Plus className="mr-2 h-4 w-4" />
              {t("createCustomButton")}
            </Button>
          </Link>
        ),
      }}
      subheader={
        <>
          <SearchInput urlParamName="search" urlPath="/mcp-servers" />
          <MCPHeaderTabs />
        </>
      }
    >
      <Suspense
        key={`${searchQuery}-${tab}`}
        fallback={
          <div className="flex h-32 items-center justify-center">
            <LoadingSpinner />
          </div>
        }
      >
        <MCPServersContent searchQuery={searchQuery} viewMode={tab} />
      </Suspense>
    </ContentBlock>
  );
}
