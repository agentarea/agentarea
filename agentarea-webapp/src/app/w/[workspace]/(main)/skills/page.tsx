import { listSkills } from "@/lib/api";
import { readUiPrefs } from "@/lib/ui-prefs-server";
import type { Skill } from "@/types/skill";
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
  const [resolvedSearchParams, uiPrefs, skillsRes] = await Promise.all([
    searchParams,
    readUiPrefs(),
    listSkills(),
  ]);

  // View mode: prefer URL, fall back to cookie, default to the Linear list.
  const cookieView = uiPrefs.views["view_skills"];
  const urlView = asString(resolvedSearchParams.view);
  const view: "list" | "grid" =
    urlView === "grid" || urlView === "list"
      ? urlView
      : cookieView === "grid"
        ? "grid"
        : "list";

  const orderParam = asString(resolvedSearchParams.order);
  const order: "name" | "created" =
    orderParam === "created" ? "created" : "name";

  if (skillsRes.error) {
    console.error("Failed to load skills:", skillsRes.error);
  }

  // SkillsView owns the page chrome (header, search, display).
  return (
    <SkillsView
      initial={{ view, order }}
      skills={(skillsRes.data ?? []) as Skill[]}
      loadFailed={Boolean(skillsRes.error)}
    />
  );
}
