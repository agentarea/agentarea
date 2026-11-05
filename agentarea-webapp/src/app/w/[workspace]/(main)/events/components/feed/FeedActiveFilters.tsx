"use client";

import { useTranslations } from "next-intl";
import ActiveFilters, { type ActiveFilter } from "@/components/ActiveFilters";
import SourceTypeMark from "@/components/SourceTypeMark";
import { StatusIndicator } from "@/components/ui/status-indicator";
import { useWorkspaceRouter } from "@/hooks/useWorkspaceNavigation";
import { EntityIcon } from "@/lib/entity-icons";
import { feedHref, type FeedState } from "@/lib/eventFeed";
import { sourceTypeBySlug, type SourceType } from "@/lib/sourceTypes";
import { getEventProcessingStatusPresentation } from "@/lib/status";

const ICON = "h-3.5 w-3.5";

/**
 * The filters the feed is under, one chip each (a source each), drawn as the
 * subheader draws its option. The kind is left out: the search field above
 * already shows it. The session and the sender, set from a row's link, have
 * no control in the subheader, so this is where they show.
 */
export default function FeedActiveFilters({
  state,
  streams,
  platformStreams,
  sourceTypes,
}: {
  state: FeedState;
  streams: { id: string; name: string }[];
  platformStreams: string[];
  sourceTypes: SourceType[];
}) {
  const t = useTranslations("EventsPage");
  const router = useWorkspaceRouter();
  const go = (patch: Partial<FeedState>) =>
    router.push(
      feedHref(state, { ...patch, event: undefined, before: undefined }),
      { scroll: false }
    );

  const filters: ActiveFilter[] = [];
  if (state.result) {
    const presentation = getEventProcessingStatusPresentation(state.result);
    filters.push({
      id: "result",
      label: t("list.result"),
      value: t(`result.${presentation.labelKey}`),
      icon: (
        <StatusIndicator
          size="sm"
          kind={presentation.kind}
          aria-hidden="true"
        />
      ),
      onRemove: () => go({ result: undefined }),
    });
  }
  if (state.stream) {
    const stream = streams.find((s) => s.id === state.stream);
    filters.push({
      id: "stream",
      label: t("list.stream"),
      value: platformStreams.includes(state.stream)
        ? t("streams.platformName")
        : (stream?.name ?? t("list.unknownStream")),
      icon: <EntityIcon kind="stream" className={ICON} />,
      onRemove: () => go({ stream: undefined }),
    });
  }
  for (const slug of state.source_type ?? []) {
    const type = sourceTypeBySlug(sourceTypes, slug);
    const rest = state.source_type?.filter((s) => s !== slug) ?? [];
    filters.push({
      id: `source_type:${slug}`,
      label: t("list.provider"),
      value: type?.name ?? slug,
      icon: <SourceTypeMark type={type} slug={slug} inline className={ICON} />,
      onRemove: () => go({ source_type: rest.length > 0 ? rest : undefined }),
    });
  }
  const mono = [
    ["session", t("list.session"), state.session],
    ["sender", t("list.sender"), state.sender],
  ] as const;
  for (const [key, label, value] of mono) {
    if (!value) continue;
    filters.push({
      id: key,
      label,
      value: <span className="font-mono">{value}</span>,
      onRemove: () => go({ [key]: undefined }),
    });
  }

  return (
    <div className="-mt-2 mb-3 empty:hidden">
      <ActiveFilters
        filters={filters}
        onClearAll={() =>
          router.push(feedHref({ origin: state.origin }), { scroll: false })
        }
      />
    </div>
  );
}
