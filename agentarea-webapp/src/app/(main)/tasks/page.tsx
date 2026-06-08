import type { Metadata } from "next";
import { Suspense } from "react";
import { getTranslations } from "next-intl/server";
import { cookies } from "next/headers";
import Link from "next/link";
import { Plus } from "lucide-react";
import ContentBlock from "@/components/ContentBlock/ContentBlock";
import { LoadingSpinner } from "@/components/LoadingSpinner";
import { Button } from "@/components/ui/button";
import { TasksData } from "./components/TasksData";

export const metadata: Metadata = {
  title: "Tasks",
};

interface TasksPageProps {
  searchParams: Promise<{ [key: string]: string | string[] | undefined }>;
}

function asString(value: string | string[] | undefined): string {
  return typeof value === "string" ? value : "";
}

export default async function TasksPage({ searchParams }: TasksPageProps) {
  const t = await getTranslations("TasksPage");
  const sp = await searchParams;

  // View: prefer URL, fall back to cookie, default to the Linear list.
  const cookieStore = await cookies();
  const cookieView = cookieStore.get("view_tasks")?.value;
  const urlView = asString(sp.view);
  const view: "list" | "grid" =
    urlView === "grid" || urlView === "list"
      ? urlView
      : cookieView === "grid"
        ? "grid"
        : "list";

  const groupParam = asString(sp.group);
  const group: "status" | "agent" | "none" =
    groupParam === "status" || groupParam === "agent" ? groupParam : "none";

  const orderParam = asString(sp.order);
  const order: "recent" | "cost" | "name" =
    orderParam === "cost" || orderParam === "name" ? orderParam : "recent";

  const tab = asString(sp.tab) || "all";
  const agent = asString(sp.agent);
  const search = asString(sp.search);

  return (
    <ContentBlock
      header={{
        breadcrumb: [{ label: t("title") }],
        controls: (
          <Link href="/agents">
            <Button className="shrink-0 gap-2" size="xs">
              <Plus className="h-4 w-4" />
              {t("newTask")}
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
        <TasksData initial={{ view, group, order, tab, agent, search }} />
      </Suspense>
    </ContentBlock>
  );
}
