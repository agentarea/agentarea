"use client";

import {
  useCallback,
  useEffect,
  useRef,
  useState,
  type ReactNode,
} from "react";
import { useTranslations } from "next-intl";
import type { SkillResponse } from "@/api/client/types.gen";
import { BlueprintBadge } from "@/components/ui/blueprint-badge";
import { MenuSectionLabel } from "@/components/ui/menu-row";
import type { AttachableResources } from "@/hooks/use-attachable-resources";
import { useCatalogFetchError } from "@/hooks/useCatalogFetchError";
import { useWorkspacePath } from "@/hooks/useWorkspaceNavigation";
import { ENTITY_ICONS } from "@/lib/entity-icons";
import { installSkillAction, listSkillsAction } from "@/lib/server-actions";
import { skillDisplay, type SkillDisplay } from "@/lib/skill-display";
import { PickerEmptyState, PickerRow, PickerRowsSkeleton } from "./PickerRow";

const SkillIcon = ENTITY_ICONS.skill;

const CATALOG_PAGE_SIZE = 20;
// On top of the search box's own debounce: each catalog search is a server
// action, and those run one at a time.
const CATALOG_DELAY_MS = 250;

export type SkillSearch = {
  query: string;
  setQuery: (query: string) => void;
  /** Catalog skills matching the current query; empty while it is blank. */
  catalogHits: SkillResponse[];
  catalogPending: boolean;
  catalogFailed: boolean;
};

/**
 * The query a skill picker filters by, and the catalog search behind it. The
 * catalog is searched only for a non-empty query: it holds ~150k skills, so
 * it is never listed whole.
 */
export function useSkillSearch(): SkillSearch {
  const [query, setQueryState] = useState("");
  const [catalog, setCatalog] = useState<{
    query: string;
    hits: SkillResponse[];
    failed: boolean;
  } | null>(null);
  const latest = useRef("");
  const timer = useRef<ReturnType<typeof setTimeout> | undefined>(undefined);

  useEffect(() => () => clearTimeout(timer.current), []);

  const setQuery = useCallback((next: string) => {
    setQueryState(next);
    const needle = next.trim();
    latest.current = needle;
    clearTimeout(timer.current);
    if (!needle) return;
    timer.current = setTimeout(async () => {
      let found: { hits: SkillResponse[]; failed: boolean };
      try {
        const { data, error } = await listSkillsAction({
          paginated: true,
          include_catalog: true,
          search: needle,
          page: 1,
          page_size: CATALOG_PAGE_SIZE,
        });
        found = {
          hits: (data?.items ?? []).filter((skill) => skill.is_catalog),
          failed: Boolean(error),
        };
      } catch (error) {
        console.error("Catalog skill search failed", error);
        found = { hits: [], failed: true };
      }
      if (latest.current === needle) setCatalog({ query: needle, ...found });
    }, CATALOG_DELAY_MS);
  }, []);

  const needle = query.trim();
  const current = needle && catalog?.query === needle ? catalog : null;
  return {
    query,
    setQuery,
    catalogHits: current?.hits ?? [],
    catalogPending: Boolean(needle) && !current,
    catalogFailed: current?.failed ?? false,
  };
}

type CatalogRowState =
  | { phase: "installing" }
  | { phase: "failed"; message: string };

type SkillPickerPanelProps = {
  resources: Pick<
    AttachableResources,
    "skills" | "loading" | "failed" | "refresh"
  >;
  search: SkillSearch;
  selectedIds: string[];
  onAdd: (skill: SkillResponse) => void;
  onRemove: (skillId: string) => void;
};

/**
 * The skills list of a pick-several sheet: the workspace's skills, and for a
 * search, the catalog's matches under them. Ticking a catalog skill installs it
 * into the workspace first, then attaches the installed copy.
 */
export function SkillPickerPanel({
  resources,
  search,
  selectedIds,
  onAdd,
  onRemove,
}: SkillPickerPanelProps) {
  const t = useTranslations("Pickers");
  const catalogFetchError = useCatalogFetchError();
  const inWorkspace = useWorkspacePath();
  const [installed, setInstalled] = useState<SkillResponse[]>([]);
  const [catalogRows, setCatalogRows] = useState<
    Record<string, CatalogRowState>
  >({});
  // An install resolves after later renders; attach through the latest
  // handler, not the one that was current when the row was ticked.
  const onAddRef = useRef(onAdd);
  useEffect(() => {
    onAddRef.current = onAdd;
  });

  const workspaceSkills = [
    ...resources.skills,
    ...installed.filter(
      (skill) => !resources.skills.some((item) => item.id === skill.id)
    ),
  ];
  const known = new Set(
    workspaceSkills.flatMap((skill) =>
      skill.registry_item_id ? [skill.id, skill.registry_item_id] : [skill.id]
    )
  );
  const catalogHits = search.catalogHits.filter(
    (skill) =>
      !known.has(skill.id) &&
      !(skill.registry_item_id && known.has(skill.registry_item_id))
  );

  const needle = search.query.trim().toLowerCase();
  const workspaceRows = workspaceSkills
    .map((skill) => ({ skill, display: skillDisplay(skill) }))
    .filter(
      ({ skill, display }) =>
        !needle ||
        [display.title, display.subtitle, display.ref, skill.name].some(
          (text) => text?.toLowerCase().includes(needle)
        )
    );

  const setRow = (id: string, state: CatalogRowState | null) =>
    setCatalogRows((rows) => {
      const next = { ...rows };
      if (state) next[id] = state;
      else delete next[id];
      return next;
    });

  async function install(hit: SkillResponse) {
    if (catalogRows[hit.id]?.phase === "installing") return;
    setRow(hit.id, { phase: "installing" });
    const label = t("catalogInstallFailed");
    try {
      const result = await installSkillAction(hit.id);
      if (result.error || !result.data) {
        setRow(hit.id, {
          phase: "failed",
          message: catalogFetchError(result, label),
        });
        return;
      }
      const skill = result.data;
      setInstalled((list) => [...list, skill]);
      setRow(hit.id, null);
      onAddRef.current(skill);
    } catch (error) {
      console.error("Failed to install catalog skill", error);
      setRow(hit.id, {
        phase: "failed",
        message: catalogFetchError({ error }, label),
      });
    }
  }

  if (resources.loading) return <PickerRowsSkeleton />;

  if (resources.failed.includes("skills")) {
    return (
      <PickerEmptyState
        iconsType="skills"
        title={t("loadFailed")}
        action={{ label: t("refresh"), onClick: resources.refresh }}
      />
    );
  }

  if (!needle && !workspaceSkills.length) {
    return (
      <PickerEmptyState
        iconsType="skills"
        title={t("emptySkillsTitle")}
        description={t("emptySkillsHint")}
        action={{
          label: t("manageSkills"),
          // A new tab: leaving would drop whatever is being written here.
          onClick: () =>
            window.open(
              inWorkspace("/skills/create"),
              "_blank",
              "noopener,noreferrer"
            ),
        }}
      />
    );
  }

  const catalogSettled = !search.catalogPending;
  if (
    !workspaceRows.length &&
    catalogSettled &&
    !search.catalogFailed &&
    !catalogHits.length
  ) {
    return (
      <PickerEmptyState
        iconsType="skills"
        title={t("nothingFoundTitle")}
        description={t("nothingFound", { query: search.query })}
      />
    );
  }

  const icon = <SkillIcon strokeWidth={1.85} />;

  return (
    <>
      {workspaceRows.length ? (
        <>
          <div className="px-3">
            <MenuSectionLabel>
              {t("skillsHeading")} ({workspaceRows.length})
            </MenuSectionLabel>
          </div>
          {workspaceRows.map(({ skill, display }) => {
            const selected = selectedIds.includes(skill.id);
            return (
              <PickerRow
                key={skill.id}
                selected={selected}
                onToggle={() => (selected ? onRemove(skill.id) : onAdd(skill))}
                icon={icon}
                title={display.title}
                subtitle={skillSubtitle(display)}
              />
            );
          })}
        </>
      ) : null}

      {needle ? (
        search.catalogPending ? (
          <div className={workspaceRows.length ? "mt-2" : undefined}>
            <PickerRowsSkeleton rows={3} />
          </div>
        ) : search.catalogFailed || catalogHits.length ? (
          <div className={workspaceRows.length ? "mt-2" : undefined}>
            <div className="px-3">
              <MenuSectionLabel>
                {t("catalogHeading")}
                {catalogHits.length ? ` (${catalogHits.length})` : null}
              </MenuSectionLabel>
            </div>
            {search.catalogFailed ? (
              <p role="alert" className="px-5 py-2 text-xs text-destructive">
                {t("catalogSearchFailed")}
              </p>
            ) : null}
            {catalogHits.map((hit) => {
              const display = skillDisplay(hit);
              const state = catalogRows[hit.id];
              return (
                <PickerRow
                  key={hit.id}
                  selected={false}
                  pending={state?.phase === "installing"}
                  onToggle={() => install(hit)}
                  icon={icon}
                  title={
                    <span className="flex min-w-0 items-center gap-1.5">
                      <span className="truncate">{display.title}</span>
                      <BlueprintBadge>{t("catalogBadge")}</BlueprintBadge>
                    </span>
                  }
                  subtitle={
                    state?.phase === "failed" ? (
                      <span
                        role="alert"
                        title={state.message}
                        className="text-destructive"
                      >
                        {state.message}
                      </span>
                    ) : state?.phase === "installing" ? (
                      t("catalogInstalling")
                    ) : (
                      skillSubtitle(display)
                    )
                  }
                />
              );
            })}
          </div>
        ) : null
      ) : null}
    </>
  );
}

/** The repo (or description) and the short hash, as a skill row's second line. */
export function skillSubtitle({ subtitle, ref }: SkillDisplay): ReactNode {
  if (!subtitle && !ref) return null;
  return (
    <>
      {subtitle}
      {subtitle && ref ? " · " : null}
      {ref ? <span className="font-mono">{ref}</span> : null}
    </>
  );
}
