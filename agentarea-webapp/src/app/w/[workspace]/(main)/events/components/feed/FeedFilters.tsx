"use client";

import { useId, useState, type ReactNode } from "react";
import { useTranslations } from "next-intl";
import { SlidersHorizontal, X } from "lucide-react";
import type { FeedFacetsResponse } from "@/api/client/types.gen";
import SourceTypeMark from "@/components/SourceTypeMark";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { MenuRow, MenuSectionLabel } from "@/components/ui/menu-row";
import {
  Sheet,
  SheetContent,
  SheetHeader,
  SheetTitle,
} from "@/components/ui/sheet";
import { StatusIndicator } from "@/components/ui/status-indicator";
import { Switch } from "@/components/ui/switch";
import { useWorkspaceRouter } from "@/hooks/useWorkspaceNavigation";
import { EntityIcon } from "@/lib/entity-icons";
import { feedHref, PROCESSING_RESULTS, type FeedState } from "@/lib/eventFeed";
import { sourceTypeBySlug, type SourceType } from "@/lib/sourceTypes";
import { getEventProcessingStatusPresentation } from "@/lib/status";

interface FiltersProps {
  state: FeedState;
  facets: FeedFacetsResponse | null;
  streams: { id: string; name: string }[];
  sourceTypes: SourceType[];
  /** Whether the platform's own events are shown, and whether the view's filter decides it. */
  platform: { shown: boolean; forced: boolean };
}

function Count({ value }: { value: number | undefined }) {
  return (
    <span className="text-xs tabular-nums text-muted-foreground">
      {value ?? 0}
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
    <div className="flex items-center gap-1 rounded-md border border-zinc-200 px-2 py-1 text-xs dark:border-zinc-700">
      <span className="text-muted-foreground">{label}</span>
      <span className="min-w-0 flex-1 truncate font-mono">{value}</span>
      <Button
        size="xs"
        variant="ghost"
        aria-label={label}
        onClick={onClear}
        className="h-5 px-0.5"
      >
        <X />
      </Button>
    </div>
  );
}

/** The feed's filters; every choice is a URL, so a view can be shared. */
function Filters({
  state,
  facets,
  streams,
  sourceTypes,
  platform,
  onNavigate,
}: FiltersProps & { onNavigate?: () => void }) {
  const t = useTranslations("EventsPage");
  const router = useWorkspaceRouter();
  const platformSwitch = useId();
  const [kind, setKind] = useState(state.kind ?? "");
  const go = (patch: Partial<FeedState>) => {
    router.push(
      feedHref(state, { ...patch, event: undefined, before: undefined }),
      {
        scroll: false,
      }
    );
    onNavigate?.();
  };
  const providers = Object.entries(facets?.source_types ?? {}).sort(
    (a, b) => b[1] - a[1]
  );
  const anyFilter = Boolean(
    state.stream ||
      state.source_type ||
      state.kind ||
      state.result ||
      state.session ||
      state.sender
  );

  const section = (title: string, children: ReactNode) => (
    <div className="space-y-0.5">
      <MenuSectionLabel>{title}</MenuSectionLabel>
      {children}
    </div>
  );

  return (
    <div className="space-y-4">
      <div className="flex items-center justify-between gap-2 px-2">
        <Label
          htmlFor={platformSwitch}
          className="text-[12.5px] font-normal text-foreground/80"
        >
          {t("list.showPlatform")}
        </Label>
        <Switch
          id={platformSwitch}
          size="xs"
          checked={platform.shown}
          disabled={platform.forced}
          onCheckedChange={(on) => go({ platform: on ? "1" : undefined })}
        />
      </div>
      {(state.session || state.sender) && (
        <div className="space-y-1.5">
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
        </div>
      )}
      {section(
        t("list.result"),
        <>
          <MenuRow
            label={t("result.all")}
            selected={!state.result}
            onClick={() => go({ result: undefined })}
          />
          {PROCESSING_RESULTS.map((result) => {
            const presentation = getEventProcessingStatusPresentation(result);
            return (
              <MenuRow
                key={result}
                icon={
                  <StatusIndicator
                    size="sm"
                    kind={presentation.kind}
                    aria-hidden="true"
                  />
                }
                label={t(`result.${presentation.labelKey}`)}
                selected={state.result === result}
                onClick={() => go({ result })}
              />
            );
          })}
        </>
      )}
      {section(
        t("list.stream"),
        <>
          <MenuRow
            label={t("list.all")}
            selected={!state.stream}
            onClick={() => go({ stream: undefined })}
          />
          {streams.map((stream) => (
            <MenuRow
              key={stream.id}
              icon={<EntityIcon kind="stream" className="h-3.5 w-3.5" />}
              label={<span className="truncate">{stream.name}</span>}
              selected={state.stream === stream.id}
              onClick={() => go({ stream: stream.id })}
              trailing={<Count value={facets?.streams[stream.id]} />}
            />
          ))}
        </>
      )}
      {providers.length > 0 &&
        section(
          t("list.provider"),
          <>
            <MenuRow
              label={t("list.all")}
              selected={!state.source_type}
              onClick={() => go({ source_type: undefined })}
            />
            {providers.map(([slug, count]) => {
              const type = sourceTypeBySlug(sourceTypes, slug);
              return (
                <MenuRow
                  key={slug}
                  icon={
                    <SourceTypeMark
                      type={type}
                      slug={slug}
                      inline
                      className="h-3.5 w-3.5"
                    />
                  }
                  label={<span className="truncate">{type?.name ?? slug}</span>}
                  selected={state.source_type === slug}
                  onClick={() => go({ source_type: slug })}
                  trailing={<Count value={count} />}
                />
              );
            })}
          </>
        )}
      {section(
        t("list.kind"),
        <form
          className="px-1 pt-1"
          onSubmit={(e) => {
            e.preventDefault();
            go({ kind: kind.trim() || undefined });
          }}
        >
          <Input
            value={kind}
            onChange={(e) => setKind(e.target.value)}
            placeholder={t("list.kindPlaceholder")}
            aria-label={t("list.kind")}
            className="h-8 font-mono text-xs"
          />
        </form>
      )}
      {anyFilter && (
        <Button
          size="xs"
          variant="link"
          className="px-2"
          onClick={() => {
            setKind("");
            router.push(feedHref({ platform: state.platform }), {
              scroll: false,
            });
            onNavigate?.();
          }}
        >
          {t("list.clear")}
        </Button>
      )}
    </div>
  );
}

/** The rail beside the feed on a wide screen, a sheet behind a button on a phone. */
export default function FeedFilters(props: FiltersProps) {
  const t = useTranslations("EventsPage.list");
  const [open, setOpen] = useState(false);
  const { state } = props;
  const active = [
    state.stream,
    state.source_type,
    state.kind,
    state.result,
    state.session,
    state.sender,
  ].filter(Boolean).length;
  return (
    <>
      <aside className="hidden lg:sticky lg:top-0 lg:block lg:self-start">
        <Filters {...props} />
      </aside>
      <div className="lg:hidden">
        <Button
          size="sm"
          variant="outline"
          className="gap-2"
          onClick={() => setOpen(true)}
        >
          <SlidersHorizontal />
          {t("filters")}
          {active > 0 && <span className="tabular-nums">({active})</span>}
        </Button>
        <Sheet open={open} onOpenChange={setOpen}>
          <SheetContent
            aria-describedby={undefined}
            side="left"
            className="overflow-y-auto"
          >
            <SheetHeader>
              <SheetTitle>{t("filters")}</SheetTitle>
            </SheetHeader>
            <div className="mt-4">
              <Filters {...props} onNavigate={() => setOpen(false)} />
            </div>
          </SheetContent>
        </Sheet>
      </div>
    </>
  );
}
