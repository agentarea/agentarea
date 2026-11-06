"use client";

import { use, useState } from "react";
import { useTranslations } from "next-intl";
import { useSearchParams } from "next/navigation";
import {
  Cpu,
  Globe,
  Layers,
  ListFilter,
  Shapes,
  SlidersHorizontal,
} from "lucide-react";
import SearchInput from "@/components/SearchInput";
import SourceTypeMark from "@/components/SourceTypeMark";
import SubheaderToolbar from "@/components/SubheaderToolbar";
import ToolbarSelect, {
  ToolbarMultiSelect,
  ToolbarMultiSelectRows,
  type ToolbarMultiSelectProps,
  type ToolbarSelectProps,
} from "@/components/ToolbarSelect";
import {
  MenuRow,
  MenuSectionLabel,
  MenuSeparator,
} from "@/components/ui/menu-row";
import {
  Popover,
  PopoverContent,
  PopoverTrigger,
} from "@/components/ui/popover";
import { StatusIndicator } from "@/components/ui/status-indicator";
import { ToolbarButton } from "@/components/ui/toolbar";
import { useWorkspaceRouter } from "@/hooks/useWorkspaceNavigation";
import { EntityIcon } from "@/lib/entity-icons";
import {
  FEED_ORIGINS,
  feedHref,
  feedOrigin,
  originPatch,
  parseFeedState,
  PLATFORM_SOURCE_TYPE,
  PROCESSING_RESULTS,
  type FeedOrigin,
  type FeedState,
} from "@/lib/eventFeed";
import { sourceTypeBySlug, type SourceType } from "@/lib/sourceTypes";
import { getEventProcessingStatusPresentation } from "@/lib/status";
import EventsSectionTabs from "../EventsSectionTabs";

const ALL = "all";
const ICON = "h-3.5 w-3.5";

type Filter = Pick<
  ToolbarSelectProps<string>,
  "label" | "groups" | "value" | "onChange"
> & {
  /** The value that filters nothing; `all` unless said. */
  idle?: string;
};

const ORIGIN_ICON: Record<FeedOrigin, typeof Globe> = {
  outside: Globe,
  all: Layers,
  platform: Cpu,
};

/**
 * The URL's query as the feed state reads it: a repeated key (several
 * sources) as a list, any other as its one value.
 */
function queryRecord(params: URLSearchParams) {
  const record: Record<string, string | string[]> = {};
  for (const key of new Set(params.keys())) {
    const values = params.getAll(key);
    record[key] = values.length > 1 ? values : values[0];
  }
  return record;
}

/** The feed's filters in one menu, a section each: the subheader when the selects do not fit. */
function FiltersMenu({
  filters,
  sources,
}: {
  filters: Filter[];
  sources: ToolbarMultiSelectProps<string>;
}) {
  const t = useTranslations("EventsPage.list");
  const [open, setOpen] = useState(false);
  const active =
    filters.filter((filter) => filter.value !== (filter.idle ?? ALL)).length +
    (sources.values.length > 0 ? 1 : 0);
  return (
    <Popover open={open} onOpenChange={setOpen}>
      <PopoverTrigger asChild>
        <ToolbarButton
          active={open}
          aria-label={t("filters")}
          className="feed-filters-menu"
        >
          <SlidersHorizontal className="h-3.5 w-3.5 text-muted-foreground" />
          {/* Icon-only on a phone, as DisplayMenu. */}
          <span className="max-sm:sr-only">{t("filters")}</span>
          {active > 0 && (
            <span className="rounded-full bg-muted px-[7px] text-[11.5px] leading-[17px] tabular-nums text-muted-foreground">
              {active}
            </span>
          )}
        </ToolbarButton>
      </PopoverTrigger>
      <PopoverContent
        align="end"
        className="max-h-[var(--radix-popover-content-available-height)] w-64 overflow-y-auto p-1.5"
      >
        {filters.map((filter, index) => (
          <div key={filter.label}>
            {index > 0 && <MenuSeparator />}
            <MenuSectionLabel>{filter.label}</MenuSectionLabel>
            {filter.groups
              .flatMap((group) =>
                Array.isArray(group) ? group : group.options
              )
              .map((option) => (
                <MenuRow
                  key={option.value}
                  icon={option.icon}
                  label={option.label}
                  selected={option.value === filter.value}
                  onClick={() => {
                    setOpen(false);
                    if (option.value !== filter.value) {
                      filter.onChange(option.value);
                    }
                  }}
                />
              ))}
          </div>
        ))}
        <MenuSeparator />
        <MenuSectionLabel>{sources.label}</MenuSectionLabel>
        <ToolbarMultiSelectRows {...sources} />
      </PopoverContent>
    </Popover>
  );
}

/**
 * The feed's subheader: the section switch, the kind search, then whose
 * events (from outside, with the platform's, the platform's alone), result,
 * stream and source. Every
 * choice is a URL, so a view can be shared; it reads the view from the URL
 * itself, so it stays mounted while the rows below reload.
 */
export default function FeedToolbar({
  streams,
  platformStreams,
  sourceTypes,
  sourceCounts,
}: {
  streams: { id: string; name: string }[];
  platformStreams: string[];
  sourceTypes: SourceType[];
  /** Events per source under the other filters; still to come while loading. */
  sourceCounts?: Promise<{ counts: Record<string, number>; capped: boolean }>;
}) {
  const t = useTranslations("EventsPage");
  const router = useWorkspaceRouter();
  const searchParams = useSearchParams();
  const state = parseFeedState(queryRecord(searchParams));
  const facets = sourceCounts ? use(sourceCounts) : undefined;
  // The sources the view has events from, most first, as the feed counts
  // them; a picked one stays in the list with nothing left under it.
  const picked = state.source_type ?? [];
  const sourceSlugs = [
    ...Object.entries(facets?.counts ?? {})
      .sort((a, b) => b[1] - a[1])
      .map(([slug]) => slug),
    ...picked,
  ].filter(
    (slug, index, all) =>
      slug !== PLATFORM_SOURCE_TYPE && all.indexOf(slug) === index
  );
  const go = (patch: Partial<FeedState>) =>
    router.push(
      feedHref(state, { ...patch, event: undefined, before: undefined }),
      { scroll: false }
    );
  // Picking a source or a stream from the platform-only view widens it to
  // outside and platform: a picked source joins the platform's events
  // (`feedApiQuery` asks for both); a stream narrows to that stream.
  const leavePlatformOnly = (): Partial<FeedState> =>
    state.origin === "platform" ? { origin: "all" } : {};

  const outsideStreams = streams.filter(
    (stream) => !platformStreams.includes(stream.id)
  );

  const filters: Filter[] = [
    {
      label: t("toolbar.origin"),
      idle: "outside",
      groups: [
        FEED_ORIGINS.map((origin) => {
          const Icon = ORIGIN_ICON[origin];
          return {
            value: origin,
            label: t(`toolbar.origins.${origin}`),
            // "Outside and platform" is every event: the button says so in
            // fewer words, the row keeps the name that explains it.
            ...(origin === "all" && {
              triggerLabel: t("toolbar.allEvents"),
            }),
            icon: <Icon className={ICON} />,
          };
        }),
      ],
      value: feedOrigin(state, platformStreams),
      onChange: (value) => {
        const origin = FEED_ORIGINS.find((o) => o === value);
        if (origin) go(originPatch(state, platformStreams, origin));
      },
    },
    {
      label: t("list.result"),
      groups: [
        [
          {
            value: ALL,
            label: t("result.all"),
            // Unfiltered, the button names the filter (as Linear does).
            triggerLabel: t("list.result"),
            icon: <ListFilter className={ICON} />,
          },
        ],
        PROCESSING_RESULTS.map((result) => {
          const presentation = getEventProcessingStatusPresentation(result);
          return {
            value: result,
            label: t(`result.${presentation.labelKey}`),
            icon: (
              <StatusIndicator
                size="sm"
                kind={presentation.kind}
                aria-hidden="true"
              />
            ),
          };
        }),
      ],
      value: state.result ?? ALL,
      onChange: (value) =>
        go({ result: PROCESSING_RESULTS.find((r) => r === value) }),
    },
  ];
  // A workspace with no stream of its own has nothing to pick here: no
  // dropdown with a lone "All".
  if (outsideStreams.length > 0) {
    filters.push({
      label: t("list.stream"),
      groups: [
        [
          {
            value: ALL,
            label: t("list.all"),
            triggerLabel: t("list.stream"),
            icon: <EntityIcon kind="stream" className={ICON} />,
          },
        ],
        // The platform's stream is "Origin: platform only", not a stream to
        // pick here: two controls for one thing would argue.
        outsideStreams.map((stream) => ({
          value: stream.id,
          label: <span className="truncate">{stream.name}</span>,
          icon: <EntityIcon kind="stream" className={ICON} />,
        })),
      ],
      value: state.stream ?? ALL,
      onChange: (value) =>
        go({
          stream: value === ALL ? undefined : value,
          ...leavePlatformOnly(),
        }),
    });
  }
  const sources: ToolbarMultiSelectProps<string> = {
    label: t("list.provider"),
    all: {
      label: t("list.all"),
      triggerLabel: t("list.provider"),
      icon: <Shapes className={ICON} />,
    },
    // The platform's own source is "Origin" too, so it is not offered here.
    options: sourceSlugs.map((slug) => {
      const type = sourceTypeBySlug(sourceTypes, slug);
      const name = type?.name ?? slug;
      const count = facets?.counts[slug];
      return {
        value: slug,
        label: (
          <span className="flex min-w-0 items-center gap-3">
            <span className="flex-1 truncate">{name}</span>
            {count !== undefined && (
              <span className="text-xs tabular-nums text-muted-foreground">
                {count}
                {facets?.capped && "+"}
              </span>
            )}
          </span>
        ),
        triggerLabel: name,
        icon: (
          <SourceTypeMark type={type} slug={slug} inline className={ICON} />
        ),
      };
    }),
    values: state.source_type ?? [],
    onChange: (values) =>
      go({
        source_type: values.length > 0 ? values : undefined,
        ...leavePlatformOnly(),
      }),
    countLabel: (count) => t("toolbar.sourcesCount", { count }),
  };

  return (
    // The subheader's own width decides whether the selects fit (globals.css,
    // `feed-toolbar`), not the screen's: the sidebar takes its share.
    <div className="feed-toolbar-cq flex h-full w-full min-w-0 flex-1">
      <SubheaderToolbar
        categories={<EventsSectionTabs />}
        search={
          <SearchInput
            urlParamName="kind"
            urlPath="/events"
            resetParamNames={["event", "before"]}
            placeholder={t("toolbar.kindPlaceholder")}
          />
        }
        controls={
          <>
            {/* The four selects while the subheader has room for them beside
              the section tabs and the search; the menu below otherwise. */}
            <div className="feed-filters-inline items-center gap-1">
              {filters.map((filter) => (
                <ToolbarSelect<string> key={filter.label} {...filter} />
              ))}
              <ToolbarMultiSelect<string> {...sources} />
            </div>
            <FiltersMenu filters={filters} sources={sources} />
          </>
        }
      />
    </div>
  );
}
