"use client";

import { useCallback, useMemo, useState } from "react";
import { useTranslations } from "next-intl";
import { useSearchParams } from "next/navigation";
import { ArrowDownAZ, Clock } from "lucide-react";
import CatalogSuggestions from "@/components/CatalogSuggestions";
import ContentBlock from "@/components/ContentBlock";
import DisplayMenu from "@/components/DisplayMenu";
import EmptyState from "@/components/EmptyState";
import HeaderTabs from "@/components/HeaderTabs";
import SkillsScene from "@/components/illustrations/SkillsScene";
import SearchInput from "@/components/SearchInput";
import SubheaderToolbar from "@/components/SubheaderToolbar";
import { MenuRow, MenuSectionLabel } from "@/components/ui/menu-row";
import { useViewerCapabilities } from "@/components/ViewerCapabilities";
import {
  useWorkspacePathname,
  useWorkspaceRouter,
} from "@/hooks/useWorkspaceNavigation";
import { setUiView } from "@/lib/ui-prefs-client";
import type { Skill } from "@/types/skill";
import { getValidTimestamp } from "@/utils/dateUtils";
import CreateSkillButton from "./CreateSkillButton";
import SkillRow from "./SkillRow";
import SkillsCard from "./SkillsCard";
import {
  UpdateAllSkillsButton,
  UpdateAllSkillsResults,
  useUpdateAllSkills,
} from "./UpdateAllSkills";

type OrderKey = "name" | "created";
type ViewKey = "list" | "grid";

interface InitialState {
  view: ViewKey;
  order: OrderKey;
}

// URL params the page keeps in sync, with the value that leaves them out.
const URL_DEFAULTS = {
  view: "list",
  order: "name",
  search: "",
};
type UrlKey = keyof typeof URL_DEFAULTS;

export default function SkillsView({
  initial,
  skills,
  loadFailed,
}: {
  initial: InitialState;
  skills: Skill[];
  loadFailed: boolean;
}) {
  const router = useWorkspaceRouter();
  const pathname = useWorkspacePathname();
  const searchParams = useSearchParams();
  const t = useTranslations("SkillsPage");
  const { canAdminister } = useViewerCapabilities();

  // view state (URL-shareable)
  const [view, setView] = useState<ViewKey>(initial.view);
  const [order, setOrder] = useState<OrderKey>(initial.order);
  // The SearchInput in the subheader owns `?search=`; the list reads it back.
  const search = searchParams.get("search") ?? "";

  // The server renders the list; after an update it renders it again.
  const reload = useCallback(() => router.refresh(), [router]);
  const updateAll = useUpdateAllSkills(reload);
  const hasUpdates = skills.some((s) => s.update_available);

  // Sync the shareable bits of state into the URL without a navigation.
  const syncUrl = useCallback(
    (next: Partial<Record<UrlKey, string>>) => {
      const params = new URLSearchParams(searchParams.toString());
      for (const [key, value] of Object.entries(next) as [UrlKey, string][]) {
        if (value && value !== URL_DEFAULTS[key]) params.set(key, value);
        else params.delete(key);
      }
      const query = params.toString();
      router.replace(query ? `${pathname}?${query}` : pathname, {
        scroll: false,
      });
    },
    [searchParams, router, pathname]
  );

  const visible = useMemo(() => {
    const q = search.trim().toLowerCase();
    if (!q) return skills;
    return skills.filter((s) =>
      `${s.name} ${s.description ?? ""}`.toLowerCase().includes(q)
    );
  }, [skills, search]);

  const sortItems = useCallback(
    (arr: Skill[]) => {
      const out = [...arr];
      if (order === "name") {
        out.sort((a, b) => a.name.localeCompare(b.name));
      } else {
        out.sort(
          (a, b) =>
            (getValidTimestamp(b.created_at) ?? 0) -
            (getValidTimestamp(a.created_at) ?? 0)
        );
      }
      return out;
    },
    [order]
  );

  const sorted = useMemo(() => sortItems(visible), [sortItems, visible]);

  // ---- toolbar control helpers ----
  const onView = (value: ViewKey) => {
    setView(value);
    setUiView("view_skills", value);
    syncUrl({ view: value });
  };
  const onOrder = (value: OrderKey) => {
    setOrder(value);
    syncUrl({ order: value });
  };
  const clearSearch = () => syncUrl({ search: "" });

  return (
    <ContentBlock
      header={{
        breadcrumb: [{ label: t("title") }],
        controls: (
          <div className="flex items-center gap-2">
            {canAdminister && hasUpdates && (
              <UpdateAllSkillsButton
                state={updateAll.state}
                onRun={updateAll.run}
              />
            )}
            <CreateSkillButton />
          </div>
        ),
      }}
      subheader={
        <SubheaderToolbar
          search={
            <SearchInput
              urlParamName="search"
              delay={250}
              placeholder={t("searchPlaceholder")}
            />
          }
          controls={
            <>
              <DisplayMenu accessibleLabel={t("display.accessibleLabel")}>
                <MenuSectionLabel>{t("display.ordering")}</MenuSectionLabel>
                <MenuRow
                  icon={<ArrowDownAZ className="h-3.5 w-3.5" />}
                  label={t("display.name")}
                  selected={order === "name"}
                  onClick={() => onOrder("name")}
                />
                <MenuRow
                  icon={<Clock className="h-3.5 w-3.5" />}
                  label={t("display.created")}
                  selected={order === "created"}
                  onClick={() => onOrder("created")}
                />
              </DisplayMenu>
              <HeaderTabs
                value={view}
                onChange={(v) => onView(v as ViewKey)}
                tabs={[
                  { value: "list", label: "List view" },
                  { value: "grid", label: "Grid view" },
                ]}
              />
            </>
          }
        />
      }
      className="p-0"
    >
      {/* The size container lets the rows drop columns as the panel narrows. */}
      <div className="skills-cq">
        {(updateAll.state.phase === "done" ||
          updateAll.state.phase === "failed") && (
          <div className="px-4 pt-4">
            <UpdateAllSkillsResults
              state={updateAll.state}
              onDismiss={updateAll.dismiss}
            />
          </div>
        )}
        {loadFailed ? (
          <div className="flex h-64 items-center justify-center text-destructive">
            {t("error.loadSkills")}
          </div>
        ) : skills.length === 0 ? (
          <div className="space-y-4 p-4">
            <EmptyState
              title={t("noSkills")}
              visual={<SkillsScene />}
              description={t("noSkillsDescription")}
              hints={[
                { text: t("noSkillsHintWrite"), href: "/skills/create" },
                { text: t("noSkillsHintImport"), href: "/skills/create" },
                {
                  text: t("noSkillsHintInstall"),
                  href: "/explore?type=skills",
                },
              ]}
              action={{
                label: t("addSkill"),
                onClick: () => router.push("/skills/create"),
              }}
            />
            <CatalogSuggestions type="skills" />
          </div>
        ) : visible.length === 0 ? (
          <div className="p-4">
            <EmptyState
              title={t("emptyHere")}
              description={t("emptyHereDescription")}
              iconsType="skills"
              action={{ label: t("filters.clear"), onClick: clearSearch }}
            />
          </div>
        ) : view === "grid" ? (
          <div
            className="grid gap-3 p-4"
            style={{
              gridTemplateColumns: "repeat(auto-fill, minmax(264px, 1fr))",
            }}
          >
            {sorted.map((skill) => (
              <SkillsCard key={skill.id} skill={skill} onUpdated={reload} />
            ))}
          </div>
        ) : (
          <div>
            {sorted.map((skill) => (
              <SkillRow key={skill.id} skill={skill} onUpdated={reload} />
            ))}
          </div>
        )}
      </div>
    </ContentBlock>
  );
}
