"use client";

import { useState, type ReactNode } from "react";
import { useTranslations } from "next-intl";
import { ArrowUpRight } from "lucide-react";
import EmptyState from "@/components/EmptyState";
import SearchInput from "@/components/SearchInput/SearchInput";
import SubheaderToolbar from "@/components/SubheaderToolbar";
import { BlueprintBadge } from "@/components/ui/blueprint-badge";
import { CountSegmentedControl } from "@/components/ui/count-segmented-control";
import { MenuSectionLabel } from "@/components/ui/menu-row";
import {
  SheetDescription,
  SheetHeader,
  SheetTitle,
} from "@/components/ui/sheet";
import Link from "@/components/WorkspaceLink";
import {
  useAttachableResources,
  type AttachableResources,
} from "@/hooks/use-attachable-resources";
import { useWorkspacePath } from "@/hooks/useWorkspaceNavigation";
import { ENTITY_ICONS } from "@/lib/entity-icons";
import { resolveMcpRef } from "@/lib/mcp/resolveMcpRef";
import { skillDisplay } from "@/lib/skill-display";
import {
  PICKER_BARE_EMPTY_STATE,
  PickerRow,
  PickerRowsSkeleton,
} from "./PickerRow";
import type { TaskResourceRef } from "./TaskResourceAttach";

type Tab = "skills" | "mcps";

type Row = {
  id: string;
  title: string;
  subtitle: string | null;
  /** Short hash, set in mono after the subtitle. */
  ref: string | null;
  iconSrc: string | null;
  /** Everything a search may match, beyond what is shown. */
  searchText: string;
  selected: boolean;
  toggle: () => void;
};

type TaskResourcePanelProps = {
  mcps: TaskResourceRef[];
  skills: TaskResourceRef[];
  onMcpsChange: (next: TaskResourceRef[]) => void;
  onSkillsChange: (next: TaskResourceRef[]) => void;
};

/**
 * The inside of the "add to this task" sheet. Mounted only while the sheet is
 * open, so the lists are fetched when someone goes to pick from them rather
 * than on every composer render.
 */
export function TaskResourcePanel(props: TaskResourcePanelProps) {
  return (
    <TaskResourcePanelView resources={useAttachableResources()} {...props} />
  );
}

/**
 * One searchable list per kind, a checkbox per row, and nothing to confirm —
 * ticking a row attaches it. Takes its lists instead of fetching them.
 */
export function TaskResourcePanelView({
  resources,
  mcps,
  skills,
  onMcpsChange,
  onSkillsChange,
}: TaskResourcePanelProps & { resources: AttachableResources }) {
  const t = useTranslations("Pickers");
  const tCommon = useTranslations("Common");
  const inWorkspace = useWorkspacePath();
  // A new tab, inside this workspace: leaving would drop the task being
  // written.
  const openInNewTab = (path: string) =>
    window.open(inWorkspace(path), "_blank", "noopener,noreferrer");
  const [tab, setTab] = useState<Tab>("skills");
  const [query, setQuery] = useState("");

  const skillRows: Row[] = resources.skills.map((skill) => {
    const display = skillDisplay(skill);
    const selected = skills.some((item) => item.id === skill.id);
    return {
      id: skill.id,
      ...display,
      iconSrc: null,
      searchText: skill.name,
      selected,
      toggle: () =>
        onSkillsChange(
          selected
            ? skills.filter((item) => item.id !== skill.id)
            : [...skills, { id: skill.id, name: skill.name }]
        ),
    };
  });

  const mcpRows: Row[] = resources.mcpInstances.map((instance) => {
    // Same resolver the connections list uses, so a server carries the name
    // and logo you know it by.
    const resolved = resolveMcpRef(
      instance.id,
      resources.mcpInstances,
      resources.mcpServers
    );
    const iconSrc =
      resolved.status === "unresolved" ? null : (resolved.iconSrc ?? null);
    const selected = mcps.some((item) => item.id === instance.id);
    return {
      id: instance.id,
      title: resolved.displayName,
      subtitle:
        resolved.status === "instance" ? (resolved.server?.name ?? null) : null,
      ref: null,
      iconSrc,
      searchText: instance.name ?? "",
      selected,
      toggle: () =>
        onMcpsChange(
          selected
            ? mcps.filter((item) => item.id !== instance.id)
            : [
                ...mcps,
                { id: instance.id, name: instance.name, iconUrl: iconSrc },
              ]
        ),
    };
  });

  const isSkills = tab === "skills";
  const rows = isSkills ? skillRows : mcpRows;
  const needle = query.trim().toLowerCase();
  const visible = needle
    ? rows.filter((row) =>
        [row.title, row.subtitle, row.ref, row.searchText].some((text) =>
          text?.toLowerCase().includes(needle)
        )
      )
    : rows;
  const Icon = isSkills ? ENTITY_ICONS.skill : ENTITY_ICONS.mcp;
  const heading = isSkills ? t("skillsHeading") : t("mcpsHeading");
  const iconsType = isSkills ? "skills" : "mcp";

  const emptyState = (props: {
    title: string;
    description?: string;
    action?: { label: string; onClick: () => void };
  }) => (
    <div className="flex h-full flex-col justify-center">
      <EmptyState
        iconsType={iconsType}
        className={PICKER_BARE_EMPTY_STATE}
        {...props}
      />
    </div>
  );

  // Only what is picked; a "0" on every untouched tab would be noise.
  const selectedCount = (count: number) => (count > 0 ? count : undefined);

  let body: ReactNode;
  if (resources.loading) {
    body = <PickerRowsSkeleton />;
  } else if (resources.failed.includes(tab)) {
    body = emptyState({
      title: t("loadFailed"),
      action: { label: t("refresh"), onClick: resources.refresh },
    });
  } else if (!rows.length) {
    body = isSkills
      ? emptyState({
          title: t("emptySkillsTitle"),
          description: t("emptySkillsHint"),
          action: {
            label: t("manageSkills"),
            onClick: () => openInNewTab("/skills/create"),
          },
        })
      : emptyState({
          title: t("emptyMcpsTitle"),
          description: t("emptyMcpsHint"),
          action: {
            label: t("manageMcps"),
            onClick: () => openInNewTab("/connections"),
          },
        });
  } else if (!visible.length) {
    body = emptyState({
      title: t("nothingFoundTitle"),
      description: t("nothingFound", { query }),
    });
  } else {
    body = (
      <>
        <div className="px-3">
          <MenuSectionLabel>
            {heading} ({visible.length})
          </MenuSectionLabel>
        </div>
        {visible.map((row) => (
          <PickerRow
            key={row.id}
            selected={row.selected}
            onToggle={row.toggle}
            iconScale={row.iconSrc ? 0.62 : 0.45}
            icon={
              row.iconSrc ? (
                // eslint-disable-next-line @next/next/no-img-element
                <img
                  src={row.iconSrc}
                  alt=""
                  className="h-full w-full object-contain"
                />
              ) : (
                <Icon strokeWidth={1.85} />
              )
            }
            title={row.title}
            subtitle={
              row.subtitle || row.ref ? (
                <>
                  {row.subtitle}
                  {row.subtitle && row.ref ? " · " : null}
                  {row.ref ? (
                    <span className="font-mono">{row.ref}</span>
                  ) : null}
                </>
              ) : null
            }
          />
        ))}
      </>
    );
  }

  return (
    <>
      <SheetHeader className="space-y-1 border-b px-5 pb-4 pr-12 pt-5 text-left">
        <SheetTitle className="flex items-center gap-2 text-[15px]">
          {t("attachTitle")}
          <BlueprintBadge>{t("thisRun")}</BlueprintBadge>
        </SheetTitle>
        <SheetDescription className="text-xs">
          {t("attachDescription")}
        </SheetDescription>
      </SheetHeader>

      {/* The subheader's 42px band, laid out as on a list page. */}
      <div className="flex h-[42px] shrink-0 items-center border-b px-5">
        <SubheaderToolbar
          search={
            <SearchInput
              delay={150}
              onDebouncedChange={setQuery}
              placeholder={tCommon("search")}
            />
          }
          categories={
            <CountSegmentedControl
              layoutId="task-attach-tabs"
              value={tab}
              onChange={setTab}
              items={[
                {
                  value: "skills",
                  label: t("skillsHeading"),
                  count: selectedCount(skills.length),
                },
                {
                  value: "mcps",
                  label: t("mcpsHeading"),
                  count: selectedCount(mcps.length),
                },
              ]}
            />
          }
        />
      </div>

      <div className="min-h-0 flex-1 overflow-y-auto py-2">{body}</div>

      <div className="flex items-center justify-between gap-3 border-t px-5 py-3">
        <Link
          href={isSkills ? "/skills" : "/connections"}
          target="_blank"
          rel="noopener noreferrer"
          className="inline-flex items-center gap-1 text-xs text-primary hover:underline"
        >
          {isSkills ? t("manageSkillsLink") : t("manageMcpsLink")}
          <ArrowUpRight className="h-3 w-3" />
        </Link>
        <span className="note">{t("appliesInstantly")}</span>
      </div>
    </>
  );
}
