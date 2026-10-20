"use client";

import { useState, type ComponentProps, type ReactNode } from "react";
import { useTranslations } from "next-intl";
import EmptyState from "@/components/EmptyState";
import { MenuSectionLabel } from "@/components/ui/menu-row";
import { useWorkspacePath } from "@/hooks/useWorkspaceNavigation";
import { PickerPanel } from "./PickerPanel";
import {
  PICKER_BARE_EMPTY_STATE,
  PickerRow,
  PickerRowsSkeleton,
} from "./PickerRow";

type ResourcePickerListProps<T extends { id: string }> = {
  /** The list's section label; the count of what is shown follows it. */
  heading: string;
  items: T[];
  selectedIds: string[];
  onAdd: (item: T) => void;
  onRemove: (item: T) => void;
  extractTitle: (item: T) => string;
  extractSubtitle?: (item: T) => ReactNode;
  /** The glyph on a row's tile. */
  extractIcon?: (item: T) => ReactNode;
  /** A logo for the tile, shown in place of the glyph when there is one. */
  extractIconSrc?: (item: T) => string | null | undefined;
  /** The entity's own avatar, in place of the tile. */
  renderAvatar?: (item: T) => ReactNode;
  loading: boolean;
  failed: boolean;
  onRefresh: () => void;
  iconsType?: ComponentProps<typeof EmptyState>["iconsType"];
  /** Shown when nothing is available — paired with the link that fixes that. */
  emptyTitle: string;
  emptyHint?: string;
  /** Where the empty state sends you to make one, in a new tab. */
  createText: string;
  createHref: string;
};

/**
 * One list of a pick-several sheet: the states every attach list shares
 * (loading, failed, empty-with-a-way-out, nothing found) and the rows. Each
 * surface used to spell these out again, which is how they drifted into
 * saying different things about the same data.
 */
export function ResourcePickerList<T extends { id: string }>({
  query,
  heading,
  items,
  selectedIds,
  onAdd,
  onRemove,
  extractTitle,
  extractSubtitle,
  extractIcon,
  extractIconSrc,
  renderAvatar,
  loading,
  failed,
  onRefresh,
  iconsType,
  emptyTitle,
  emptyHint,
  createText,
  createHref,
}: ResourcePickerListProps<T> & { query: string }) {
  const t = useTranslations("Pickers");
  const inWorkspace = useWorkspacePath();

  const needle = query.trim().toLowerCase();
  const visible = needle
    ? items.filter((item) => {
        const subtitle = extractSubtitle?.(item);
        return [
          extractTitle(item),
          typeof subtitle === "string" ? subtitle : null,
        ].some((text) => text?.toLowerCase().includes(needle));
      })
    : items;

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

  let body: ReactNode;
  if (loading) {
    body = <PickerRowsSkeleton />;
  } else if (failed) {
    body = emptyState({
      title: t("loadFailed"),
      action: { label: t("refresh"), onClick: onRefresh },
    });
  } else if (!items.length) {
    body = emptyState({
      title: emptyTitle,
      description: emptyHint,
      action: {
        label: createText,
        // A new tab: leaving would drop the form being filled in.
        onClick: () =>
          window.open(inWorkspace(createHref), "_blank", "noopener,noreferrer"),
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
        {visible.map((item) => {
          const selected = selectedIds.includes(item.id);
          const iconSrc = extractIconSrc?.(item);
          return (
            <PickerRow
              key={item.id}
              selected={selected}
              onToggle={() => (selected ? onRemove(item) : onAdd(item))}
              avatar={renderAvatar?.(item)}
              iconScale={iconSrc ? 0.62 : 0.45}
              icon={
                iconSrc ? (
                  // eslint-disable-next-line @next/next/no-img-element
                  <img
                    src={iconSrc}
                    alt=""
                    className="h-full w-full object-contain"
                  />
                ) : (
                  extractIcon?.(item)
                )
              }
              title={extractTitle(item)}
              subtitle={extractSubtitle?.(item)}
            />
          );
        })}
      </>
    );
  }

  return body;
}

/** A pick-several sheet over one list, in the frame of the task's attach sheet. */
export function ResourcePicker<T extends { id: string }>({
  title,
  description,
  manageText,
  manageHref,
  ...list
}: ResourcePickerListProps<T> & {
  title: ReactNode;
  description: ReactNode;
  /** The footer link to where these are managed. */
  manageText: string;
  manageHref: string;
}) {
  const [query, setQuery] = useState("");

  return (
    <PickerPanel
      title={title}
      description={description}
      onSearch={setQuery}
      manageText={manageText}
      manageHref={manageHref}
    >
      <ResourcePickerList query={query} {...list} />
    </PickerPanel>
  );
}
