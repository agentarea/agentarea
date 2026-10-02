import { cookies } from "next/headers";
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

  const scope = asString(resolvedSearchParams.network_scope);

  // SkillsView owns the page chrome (header, scope tabs, search, display): the
  // tab counts come from the same client-side fetch as the list.
  return <SkillsView initial={{ view, group, order, scope }} />;
}
