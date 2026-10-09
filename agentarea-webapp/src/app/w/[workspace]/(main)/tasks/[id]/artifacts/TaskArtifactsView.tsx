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

export type ArtifactListing =
  | { kind: "loading" }
  | { kind: "error"; message: string }
  | { kind: "ready"; files: BrowsedFile[] };

interface TaskArtifactsViewProps {
  /** Null while the task is still loading. */
  taskId: string | null;
  /**
   * Set (possibly empty, when nothing says why) when the task itself failed
   * to load; nothing else can show then.
   */
  taskError: string | null;
  listing: ArtifactListing;
  refreshing: boolean;
  onRefresh: () => void;
  fetchUrl: FetchUrlFn;
  browserState: FileBrowserState;
  onBrowserStateChange: (state: FileBrowserState) => void;
}

/** How many artifacts there are and what they are, at the toolbar's left. */
function ArtifactsSummary({ listing }: { listing: ArtifactListing }) {
  const t = useTranslations("TaskArtifactsPage");
  if (listing.kind === "loading") return null;

  return (
    <div className="flex min-w-0 items-center gap-2 text-xs text-muted-foreground">
      {listing.kind === "error" ? (
        <span className="text-foreground">{t("unavailable")}</span>
      ) : (
        <>
          <span className="shrink-0 tabular-nums text-foreground">
            {t("count", { count: listing.files.length })}
          </span>
          <span className="truncate max-lg:hidden">· {t("durable")}</span>
        </>
      )}
    </div>
  );
}

/**
 * The files a task published, in the same browser as its live sandbox files:
 * a tree by path, a preview and a download for each.
 */
export default function TaskArtifactsView({
  taskId,
  taskError,
  listing,
  refreshing,
  onRefresh,
  fetchUrl,
  browserState,
  onBrowserStateChange,
}: TaskArtifactsViewProps) {
  const t = useTranslations("TaskArtifactsPage");
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
  } else if (listing.kind === "error") {
    body = (
      <div className="px-4 py-5">
        <EmptyState
          title={t("loadFailed")}
          description={listing.message}
          action={{ label: tCommon("retry"), onClick: onRefresh }}
        />
      </div>
    );
  } else if (listing.files.length === 0) {
    // Nothing published yet; the task's working files may still be there.
    body = (
      <div className="px-4 py-5">
        <EmptyState
          title={t("empty")}
          description={t("emptyDescription")}
          action={{ label: t("openFiles"), href: `/tasks/${taskId}/files` }}
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
        rootLabel={t("treeLabel")}
      />
    );
  }

  return (
    <ContentBlock
      subheader={
        <SubheaderToolbar
          categories={<ArtifactsSummary listing={listing} />}
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
