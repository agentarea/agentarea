import type { Metadata } from "next";
import { Suspense } from "react";
import { getTranslations } from "next-intl/server";
import { cookies } from "next/headers";
import Link from "next/link";
import { Plus } from "lucide-react";
import AgentsContent from "@/app/(main)/agents/components/AgentsContent";
import ContentBlock from "@/components/ContentBlock/ContentBlock";
import { LoadingSpinner } from "@/components/LoadingSpinner";
import { Button } from "@/components/ui/button";

export const metadata: Metadata = {
  title: "Agents",
};

interface AgentsBrowsePageProps {
  searchParams: Promise<{ [key: string]: string | string[] | undefined }>;
}

function asString(value: string | string[] | undefined): string {
  return typeof value === "string" ? value : "";
}

export default async function AgentsBrowsePage({
  searchParams,
}: AgentsBrowsePageProps) {
  const t = await getTranslations("AgentsPage");
  const sp = await searchParams;

  // View: prefer URL, fall back to cookie, default to the Linear list.
  const cookieStore = await cookies();
  const cookieView = cookieStore.get("view_agents")?.value;
  const urlView = asString(sp.view);
  const view: "list" | "grid" =
    urlView === "grid" || urlView === "list"
      ? urlView
      : cookieView === "grid"
        ? "grid"
        : "list";

  const groupParam = asString(sp.group);
  const group: "status" | "model" | "none" =
    groupParam === "model" || groupParam === "none" ? groupParam : "status";

  const orderParam = asString(sp.order);
  const order: "name" | "tasks" = orderParam === "tasks" ? "tasks" : "name";

  const statusTab = asString(sp.status) || "all";
  const model = asString(sp.model);
  const search = asString(sp.search);

  return (
    <ContentBlock
      header={{
        breadcrumb: [{ label: t("browseAgents") }],
        controls: (
          <Link href="/agents/create">
            <Button
              className="shrink-0 gap-2"
              size="xs"
              data-test="deploy-button"
            >
              <Plus className="h-4 w-4" />
              {t("deployNewAgent")}
            </Button>
          </Link>
        ),
      }}
      className="p-0 overflow-hidden"
    >
      <Suspense
        fallback={
          <div className="flex h-64 items-center justify-center">
            <LoadingSpinner />
          </div>
        }
      >
        <AgentsContent
          initial={{ view, group, order, statusTab, model, search }}
        />
      </Suspense>
    </ContentBlock>
  );
}
