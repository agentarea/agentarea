import type { Metadata } from "next";
import { Suspense } from "react";
import { getTranslations } from "next-intl/server";
import { cookies } from "next/headers";
import ContentBlock from "@/components/ContentBlock";
import { LoadingSpinner } from "@/components/LoadingSpinner";
import MCPServersContent from "./components/MCPServersContent";
import { AddConnectionDropdown } from "./components/AddConnectionDropdown";

export const metadata: Metadata = {
  title: "Connections",
};

function asString(value: string | string[] | undefined): string {
  return typeof value === "string" ? value : "";
}

export default async function MCPServersPage({
  searchParams,
}: {
  searchParams: Promise<{ [key: string]: string | string[] | undefined }>;
}) {
  const t = await getTranslations("MCPServersPage");
  const resolvedSearchParams = await searchParams;

  // View mode: prefer URL, fall back to cookie, default to grid (as before).
  const cookieStore = await cookies();
  const cookieView = cookieStore.get("view_mcp-servers")?.value;
  const urlView = asString(resolvedSearchParams.view);
  const view: "list" | "grid" =
    urlView === "grid" || urlView === "list"
      ? urlView
      : cookieView === "grid"
        ? "grid"
        : "list";

  const protocolParam = asString(resolvedSearchParams.protocol);
  const tab: "all" | "mcp" | "openapi" =
    protocolParam === "mcp" || protocolParam === "openapi"
      ? protocolParam
      : "all";

  const groupParam = asString(resolvedSearchParams.group);
  const group: "none" | "status" | "type" =
    groupParam === "status" || groupParam === "type" ? groupParam : "none";

  const orderParam = asString(resolvedSearchParams.order);
  const order: "name" | "status" =
    orderParam === "status" ? "status" : "name";

  const search = asString(resolvedSearchParams.search);

  return (
    <ContentBlock
      header={{
        breadcrumb: [{ label: t("title") }],
        controls: <AddConnectionDropdown />,
      }}
      className="overflow-hidden p-0"
    >
      <Suspense
        fallback={
          <div className="flex h-32 items-center justify-center">
            <LoadingSpinner />
          </div>
        }
      >
        <MCPServersContent initial={{ view, tab, group, order, search }} />
      </Suspense>
    </ContentBlock>
  );
}
