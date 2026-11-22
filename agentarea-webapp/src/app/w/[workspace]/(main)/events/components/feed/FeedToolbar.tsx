"use client";

import type { ReactNode } from "react";
import { useTranslations } from "next-intl";
import { Eye, Layers, ListFilter, X } from "lucide-react";
import type { FeedFacetsResponse } from "@/api/client/types.gen";
import DisplayMenu from "@/components/DisplayMenu";
import SearchInput from "@/components/SearchInput";
import SourceTypeMark from "@/components/SourceTypeMark";
import SubheaderToolbar from "@/components/SubheaderToolbar";
import ToolbarSelect from "@/components/ToolbarSelect";
import { MenuRow, MenuSectionLabel } from "@/components/ui/menu-row";
import { StatusIndicator } from "@/components/ui/status-indicator";
import { ToolbarButton } from "@/components/ui/toolbar";
import { useWorkspaceRouter } from "@/hooks/useWorkspaceNavigation";
import { EntityIcon } from "@/lib/entity-icons";
import { feedHref, PROCESSING_RESULTS, type FeedState } from "@/lib/eventFeed";
import { sourceTypeBySlug, type SourceType } from "@/lib/sourceTypes";
import { getEventProcessingStatusPresentation } from "@/lib/status";

const ALL = "all";
const GLYPH = "h-3.5 w-3.5";

/** A facet count; `atLeast` when the server stopped counting, so it is a lower bound. */
function Count({
  value,
  atLeast,
}: {
  value: number | undefined;
  atLeast: boolean;
}) {
  if (atLeast && value === undefined) return null;
  return (
    <span className="shrink-0 text-xs tabular-nums text-muted-foreground">
      {value ?? 0}
      {atLeast && "+"}
    </span>
  );
}

function CountedLabel({ name, count }: { name: string; count: ReactNode }) {
  return (
    <span className="flex min-w-0 items-center gap-2">
      <span className="min-w-0 flex-1 truncate" title={name}>
        {name}
      </span>
      {count}
    </span>
  );
}

function Chip({
  label,
  value,
  onClear,
}: {
  label: string;
  value: string;
  onClear: () => void;
}) {
  return (
    <ToolbarButton
      onClick={onClear}
      aria-label={`${label}: ${value}`}
      title={value}
      className="max-w-48 border border-zinc-200 dark:border-zinc-700"
    >
      <span className="text-muted-foreground max-sm:sr-only">{label}</span>
      <span className="min-w-0 truncate font-mono">{value}</span>
      <X className="h-3.5 w-3.5 shrink-0 text-muted-foreground" />
    </ToolbarButton>
  );
}

/**
 * The feed's subheader: the kind search, then its filters, every choice a URL
 * so a view can be shared. Facet selects wait for the counts (`facets` null)
 * and stay away while there is nothing to choose between.
 */
export default function FeedToolbar({
  state,
  facets,
  streams,
  platformStreams,
  sourceTypes,
  platform,
}: {
  state: FeedState;
  facets: FeedFacetsResponse | null;
  streams: { id: string; name: string }[];
  platformStreams: string[];
  sourceTypes: SourceType[];
  /** Whether the platform's own events are shown, and whether the view's filter decides it. */
  platform: { shown: boolean; forced: boolean };
}) {
  const t = useTranslations("EventsPage");
  const router = useWorkspaceRouter();
  const go = (patch: Partial<FeedState>) =>
    router.push(
      feedHref(state, { ...patch, event: undefined, before: undefined }),
      { scroll: false }
    );
  const capped = facets?.capped ?? false;

  const streamOptions = streams.filter(
    (s) =>
      platform.shown || !platformStreams.includes(s.id) || s.id === state.stream
  );
  const providers = Object.entries(facets?.source_types ?? {}).sort(
    (a, b) => b[1] - a[1]
  );
  // The stream page's stream is where it is, not a filter to clear.
  const anyFilter = Boolean(
    state.source_type ||
      state.kind ||
      state.result ||
      state.session ||
      state.sender
  );

  return (
    <SubheaderToolbar
      search={
        <SearchInput
          urlParamName="kind"
          urlPath={feedHref({ stream: state.stream })}
          resetParamNames={["before", "event"]}
          placeholder={t("list.kindPlaceholder")}
        />
      }
      controls={
        <>
          {state.session && (
            <Chip
              label={t("list.session")}
              value={state.session}
              onClear={() => go({ session: undefined })}
            />
          )}
          {state.sender && (
            <Chip
              label={t("list.sender")}
              value={state.sender}
              onClear={() => go({ sender: undefined })}
            />
          )}
          <ToolbarSelect
            label={t("list.result")}
            value={state.result ?? ALL}
            onChange={(value) =>
              go({
                result: PROCESSING_RESULTS.find((r) => r === value),
              })
            }
            groups={[
              [
                {
                  value: ALL,
                  label: t("result.all"),
                  triggerLabel: t("list.result"),
                  icon: (
                    <ListFilter className={`${GLYPH} text-muted-foreground`} />
                  ),
                },
              ],
              PROCESSING_RESULTS.map((result) => {
                const presentation =
                  getEventProcessingStatusPresentation(result);
                return {
                  value: result,
                  label: t(`result.${presentation.labelKey}`),
                  icon: (
                    <StatusIndicator
                      kind={presentation.kind}
                      aria-hidden="true"
                    />
                  ),
                };
              }),
            ]}
          />
          {facets && (streamOptions.length > 1 || state.stream) && (
            <ToolbarSelect
              label={t("list.stream")}
              value={state.stream ?? ALL}
              onChange={(value) =>
                go({ stream: value === ALL ? undefined : value })
              }
              groups={[
                [
                  {
                    value: ALL,
                    label: t("list.all"),
                    triggerLabel: t("list.stream"),
                    icon: <EntityIcon kind="stream" className={GLYPH} />,
                  },
                ],
                streamOptions.map((stream) => ({
                  value: stream.id,
                  label: (
                    <CountedLabel
                      name={stream.name}
                      count={
                        <Count
                          value={facets.streams[stream.id]}
                          atLeast={capped}
                        />
                      }
                    />
                  ),
                  triggerLabel: stream.name,
                  icon: (
                    <EntityIcon
                      kind={
                        platformStreams.includes(stream.id)
                          ? "platformStream"
                          : "stream"
                      }
                      className={GLYPH}
                    />
                  ),
                })),
              ]}
            />
          )}
          {facets && (providers.length > 1 || state.source_type) && (
            <ToolbarSelect
              label={t("list.provider")}
              value={state.source_type ?? ALL}
              onChange={(value) =>
                go({ source_type: value === ALL ? undefined : value })
              }
              groups={[
                [
                  {
                    value: ALL,
                    label: t("list.all"),
                    triggerLabel: t("list.provider"),
                    icon: (
                      <Layers className={`${GLYPH} text-muted-foreground`} />
                    ),
                  },
                ],
                providers.map(([slug, count]) => {
                  const type = sourceTypeBySlug(sourceTypes, slug);
                  const name = type?.name ?? slug;
                  return {
                    value: slug,
                    label: (
                      <CountedLabel
                        name={name}
                        count={<Count value={count} atLeast={capped} />}
                      />
                    ),
                    triggerLabel: name,
                    icon: (
                      <SourceTypeMark
                        type={type}
                        slug={slug}
                        inline
                        className={GLYPH}
                      />
                    ),
                  };
                }),
              ]}
            />
          )}
          <DisplayMenu>
            <MenuSectionLabel>{t("list.display")}</MenuSectionLabel>
            <MenuRow
              icon={<Eye className={GLYPH} />}
              label={t("list.showPlatform")}
              selected={platform.shown}
              disabled={platform.forced}
              onClick={() => go({ platform: platform.shown ? "0" : undefined })}
            />
          </DisplayMenu>
          {anyFilter && (
            <ToolbarButton
              onClick={() =>
                router.push(
                  feedHref({ stream: state.stream, platform: state.platform }),
                  { scroll: false }
                )
              }
            >
              {t("list.clear")}
            </ToolbarButton>
          )}
        </>
      }
    />
  );
}
