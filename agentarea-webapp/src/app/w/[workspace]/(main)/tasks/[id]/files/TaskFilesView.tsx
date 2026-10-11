"use client";

import { useTranslations } from "next-intl";
import ContentBlock from "@/components/ContentBlock/ContentBlock";
import EmptyState from "@/components/EmptyState";
import {
  FileBrowser,
  type BrowsedFile,
  type FetchUrlFn,
  type FileBrowserState,
} from "@/components/files/file-browser";
import { FileBrowserSkeleton } from "@/components/files/file-browser-skeleton";
import SubheaderToolbar from "@/components/SubheaderToolbar";
import ToolbarRefreshButton from "@/components/ToolbarRefreshButton";
import { StatusIndicator } from "@/components/ui/status-indicator";
import type { StatusKind } from "@/lib/status";

/**
 * Where the task's live sandbox stands. A sandbox that was never started, or
 * one that has expired, is a stage of its life rather than a failure: only
 * `error` is something a retry could fix.
 */
export type SandboxListing =
  | { kind: "loading" }
  | { kind: "missing" }
  | { kind: "expired" }
  | { kind: "error"; message: string }
  | { kind: "ready"; files: BrowsedFile[] };

interface TaskFilesViewProps {
  /** Null while the task is still loading. */
  taskId: string | null;
  /**
   * Set (possibly empty, when nothing says why) when the task itself failed
   * to load; nothing else can show then.
   */
  taskError: string | null;
  listing: SandboxListing;
  refreshing: boolean;
  onRefresh: () => void;
  fetchUrl: FetchUrlFn;
  browserState: FileBrowserState;
  onBrowserStateChange: (state: FileBrowserState) => void;
}

const STATE_KINDS: Record<
  Exclude<SandboxListing["kind"], "loading">,
  StatusKind
> = {
  ready: "active",
  missing: "draft",
  expired: "off",
  error: "failed",
};

/** The sandbox's state and what it holds, at the left of the toolbar. */
function SandboxState({ listing }: { listing: SandboxListing }) {
  const t = useTranslations("TaskFilesPage");
  if (listing.kind === "loading") return null;

  const label = {
    ready: t("live"),
    missing: t("noSandboxShort"),
    expired: t("expiredShort"),
    error: t("unavailable"),
  }[listing.kind];

  return (
    <div className="flex min-w-0 items-center gap-2 text-xs">
      <StatusIndicator kind={STATE_KINDS[listing.kind]} size="sm">
        {label}
      </StatusIndicator>
      {listing.kind === "ready" && (
        <>
          <span className="shrink-0 tabular-nums text-muted-foreground">
            · {t("fileCount", { count: listing.files.length })}
          </span>
          <span className="truncate text-muted-foreground max-lg:hidden">
            · {t("ephemeral")}
          </span>
        </>
      )}
    </div>
  );
}

/** A task's live sandbox files, in the same browser as workspace files. */
export default function TaskFilesView({
  taskId,
  taskError,
  listing,
  refreshing,
  onRefresh,
  fetchUrl,
  browserState,
  onBrowserStateChange,
}: TaskFilesViewProps) {
  const t = useTranslations("TaskFilesPage");
  const tCommon = useTranslations("Common");

  if (taskError !== null) {
    return (
      <div className="px-4 py-5">
        <EmptyState
          title={t("taskLoadFailed")}
          description={taskError || undefined}
          iconsType="tasks"
        />
      </div>
    );
  }

  let body: React.ReactNode;
  if (!taskId || listing.kind === "loading") {
    body = <FileBrowserSkeleton />;
  } else if (listing.kind === "missing" || listing.kind === "expired") {
    // Nothing to browse, but the task's published output still is.
    body = (
      <div className="px-4 py-5">
        <EmptyState
          title={t(listing.kind === "missing" ? "noSandbox" : "expired")}
          description={t(
            listing.kind === "missing"
              ? "noSandboxDescription"
              : "expiredDescription"
          )}
          action={{
            label: t("openArtifacts"),
            href: `/tasks/${taskId}/artifacts`,
          }}
        />
      </div>
    );
  } else if (listing.kind === "error") {
    // A sandbox that cannot be reached has no tree to show either: the whole
    // tab says so, as it does for one that is missing or expired.
    body = (
      <div className="px-4 py-5">
        <EmptyState
          title={t("loadFailed")}
          description={listing.message}
          action={{ label: tCommon("retry"), onClick: onRefresh }}
        />
      </div>
    );
  } else {
    body = (
      <FileBrowser
        files={listing.files}
        state={browserState}
        onChange={onBrowserStateChange}
        fetchUrl={fetchUrl}
        emptyMessage={t("empty")}
        rootLabel={t("treeLabel")}
      />
    );
  }

  return (
    <ContentBlock
      subheader={
        <SubheaderToolbar
          categories={<SandboxState listing={listing} />}
          controls={
            <ToolbarRefreshButton
              onRefresh={onRefresh}
              refreshing={refreshing}
            />
          }
        />
      }
      className="min-h-0 overflow-hidden p-0"
    >
      {body}
    </ContentBlock>
  );
}
