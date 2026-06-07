import { getTranslations } from "next-intl/server";
import { cookies } from "next/headers";
import ContentBlock from "@/components/ContentBlock";
import CreateSkillButton from "./components/CreateSkillButton";
import SkillsView from "./components/SkillsView";

export const metadata = {
  title: "Skills",
};

function asString(value: string | string[] | undefined): string {
  return typeof value === "string" ? value : "";
}

export default async function SkillsPage({
  searchParams,
}: {
  searchParams: Promise<{ [key: string]: string | string[] | undefined }>;
}) {
  const t = await getTranslations("SkillsPage");
  const resolvedSearchParams = await searchParams;

  // View mode: prefer URL, fall back to cookie, default to the Linear list.
  const cookieStore = await cookies();
  const cookieView = cookieStore.get("view_skills")?.value;
  const urlView = asString(resolvedSearchParams.view);
  const view: "list" | "grid" =
    urlView === "grid" || urlView === "list"
      ? urlView
      : cookieView === "grid"
        ? "grid"
        : "list";

  const groupParam = asString(resolvedSearchParams.group);
  const group: "source" | "scope" | "none" =
    groupParam === "scope" || groupParam === "none" ? groupParam : "source";

  const orderParam = asString(resolvedSearchParams.order);
  const order: "name" | "created" =
    orderParam === "created" ? "created" : "name";

  const sourceTab = asString(resolvedSearchParams.source_type) || "all";
  const scope = asString(resolvedSearchParams.network_scope);
  const files = asString(resolvedSearchParams.files) || "all";
  const search = asString(resolvedSearchParams.search);

  return (
    <ContentBlock
      header={{
        breadcrumb: [{ label: t("title") }],
        controls: <CreateSkillButton />,
      }}
      className="p-0 overflow-hidden"
    >
      <SkillsView
        initial={{
          view,
          group,
          order,
          sourceTab,
          scope,
          files,
          search,
        }}
      />
    </ContentBlock>
  );
}
