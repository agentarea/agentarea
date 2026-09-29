"use client";

import { useState, type ReactNode } from "react";
import { useTranslations } from "next-intl";
import { ArrowUpRight } from "lucide-react";
import EmptyState from "@/components/EmptyState";
import Link from "@/components/WorkspaceLink";
import SearchInput from "@/components/SearchInput/SearchInput";
import { BlueprintBadge } from "@/components/ui/blueprint-badge";
import { Checkbox } from "@/components/ui/checkbox";
import { CountSegmentedControl } from "@/components/ui/count-segmented-control";
import { EntityAvatar } from "@/components/ui/entity-avatar";
import { InteractiveListRow } from "@/components/ui/interactive-list-row";
import { MenuSectionLabel } from "@/components/ui/menu-row";
import {
  SheetDescription,
  SheetHeader,
  SheetTitle,
} from "@/components/ui/sheet";
import { Skeleton } from "@/components/ui/skeleton";
import { useWorkspacePath } from "@/hooks/useWorkspaceNavigation";
import {
  useAttachableResources,
  type AttachableResources,
} from "@/hooks/use-attachable-resources";
import { ENTITY_ICONS } from "@/lib/entity-icons";
import { resolveMcpRef } from "@/lib/mcp/resolveMcpRef";
import { skillDisplay } from "@/lib/skill-display";
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

const SELECTED_TINT = "hsl(var(--primary))";

/** The shared empty state without its card — the sheet is the card here. */
const BARE_EMPTY_STATE =
  "border-0 bg-transparent p-6 shadow-none hover:bg-transparent dark:bg-transparent dark:hover:bg-transparent";


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
        className={BARE_EMPTY_STATE}
        {...props}
      />
    </div>
  );

  // Only what is picked; a "0" on every untouched tab would be noise.
  const selectedCount = (count: number) => (count > 0 ? count : undefined);

  let body: ReactNode;
  if (resources.loading) {
    body = <RowsSkeleton />;
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
          <InteractiveListRow
            key={row.id}
            onClick={row.toggle}
            pressed={row.selected}
            showIndicator={false}
            dividerClassName=""
            className="px-5 py-2"
            start={
              <EntityAvatar
                variant="soft"
                size={32}
                color={row.selected ? SELECTED_TINT : undefined}
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
                aria-hidden
              />
            }
            end={
              // The row is the control; the box only shows its state.
              <Checkbox
                checked={row.selected}
                tabIndex={-1}
                aria-hidden
                className="pointer-events-none border-zinc-300 dark:border-zinc-600 data-[state=checked]:border-primary data-[state=checked]:bg-primary data-[state=checked]:text-primary-foreground"
              />
            }
          >
            <div className="min-w-0 flex-1">
              <p className="truncate text-[13px] font-medium leading-5 text-foreground">
                {row.title}
              </p>
              {row.subtitle || row.ref ? (
                <p className="truncate text-xs leading-4 text-muted-foreground">
                  {row.subtitle}
                  {row.subtitle && row.ref ? " · " : null}
                  {row.ref ? (
                    <span className="font-mono">{row.ref}</span>
                  ) : null}
                </p>
              ) : null}
            </div>
          </InteractiveListRow>
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

      <div className="space-y-2 border-b px-5 pb-3 pt-2">
        <SearchInput
          delay={150}
          onDebouncedChange={setQuery}
          placeholder={tCommon("search")}
        />
        <CountSegmentedControl
          layoutId="task-attach-tabs"
          value={tab}
          onChange={setTab}
          className="-ml-[3px]"
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

/** Stand-in for the list while it loads: the section label and six rows. */
function RowsSkeleton() {
  return (
    <div aria-hidden className="px-5">
      <Skeleton className="mb-2 mt-1.5 h-3 w-20" />
      {Array.from({ length: 6 }).map((_, index) => (
        <div key={index} className="flex items-center gap-3 py-2">
          <Skeleton className="h-8 w-8 rounded-[9px]" />
          <div className="flex-1 space-y-1.5">
            <Skeleton className="h-3 w-2/5" />
            <Skeleton className="h-2.5 w-3/5" />
          </div>
          <Skeleton className="h-4 w-4 rounded-sm" />
        </div>
      ))}
    </div>
  );
}
