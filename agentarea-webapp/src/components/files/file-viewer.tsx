"use client";

import { useEffect, useState } from "react";
import { useFormatter, useTranslations } from "next-intl";
import {
  Bot,
  Check,
  ChevronDown,
  CircleX,
  Copy,
  Download,
  FileText,
  History,
  Loader2,
  Trash2,
  User,
} from "lucide-react";
import FormError from "@/components/FormError";
import { Button } from "@/components/ui/button";
import {
  apiErrorMessage,
  formatApiError,
  type ApiResultLike,
} from "@/lib/api-errors";
import { cn } from "@/lib/utils";
import { parseUtcTimestamp } from "@/utils/dateUtils";
import { formatFileSize } from "@/utils/fileUtils";
import {
  concatBytes,
  looksTextual,
  mediaKind,
  readProbe,
  type MediaKind,
} from "./content-sniff";
import type { BrowsedFile } from "./file-tree";
import { TextPreview } from "./text-preview";

type ViewerKind = MediaKind | "text" | "binary";

/** Read the opening bytes, then either the rest or nothing more.
 *
 * Text is shown in full, so it is read to the end. A video is handed to the
 * browser as a URL, so the transfer is cancelled once the probe has answered
 * the question — no megabytes are pulled in only to be thrown away. */
async function inspect(
  response: Response,
  declared: string | null
): Promise<{ kind: ViewerKind; text: string | null }> {
  const body = response.body;
  if (!body) return { kind: mediaKind(declared) ?? "binary", text: null };

  const reader = body.getReader();
  const chunks = await readProbe(reader);
  const head = concatBytes(chunks);

  if (!looksTextual(head)) {
    await reader.cancel();
    return { kind: mediaKind(declared) ?? "binary", text: null };
  }
  for (;;) {
    const { done, value } = await reader.read();
    if (done) break;
    chunks.push(value);
  }
  return { kind: "text", text: new TextDecoder().decode(concatBytes(chunks)) };
}

/** A picture, a clip or a recording, played by the browser from its URL. */
export function MediaPreview({
  kind,
  url,
  name,
  className,
}: {
  kind: "image" | "video" | "audio";
  url: string;
  name: string;
  className?: string;
}) {
  if (kind === "image") {
    // Not next/image: the optimiser fetches the source from the server, where
    // it carries none of the viewer's cookies, so every workspace file comes
    // back a 401 and renders broken. These are private files behind auth, not
    // assets worth optimising.
    // eslint-disable-next-line @next/next/no-img-element
    return <img src={url} alt={name} className={cn("object-contain", className)} />;
  }
  if (kind === "video") {
    return <video src={url} controls className={className} />;
  }
  return <audio src={url} controls className={className} />;
}

export type FetchUrlFn = (path: string) => Promise<ApiResultLike<string>>;

export type ArtifactEvent = {
  action: string;
  actor_type: string;
  created_by: string;
  agent_id?: string | null;
  task_id?: string | null;
  created_at: string;
  actor_display_name?: string | null;
};

export type FetchHistoryFn = (
  path: string
) => Promise<ApiResultLike<ArtifactEvent[]>>;

/** Actions the artifact audit log records. An action added to the backend and
 * not yet listed here shows its own verb rather than a missing-key label. */
const ACTION_KEYS: Record<string, string> = {
  created: "action.created",
  modified: "action.modified",
  deleted: "action.deleted",
  moved: "action.moved",
};

const UUID_PATTERN = /^[0-9a-f]{8}(?:-[0-9a-f]{4}){3}-[0-9a-f]{12}$/i;

function useProvenance(file: BrowsedFile, fetchHistory?: FetchHistoryFn) {
  const t = useTranslations("FilesPage");
  const [events, setEvents] = useState<ArtifactEvent[] | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(Boolean(fetchHistory));

  useEffect(() => {
    if (!fetchHistory) return;
    let cancelled = false;
    setEvents(null);
    setError(null);
    setLoading(true);
    (async () => {
      try {
        const result = await fetchHistory(file.path);
        if (cancelled) return;
        if (result.error || !result.data) {
          setError(apiErrorMessage(result, t("historyLoadFailed")));
        } else {
          // Newest first regardless of the order the endpoint happens to
          // return, so the summary line always names the most recent change.
          setEvents(
            [...result.data].sort((a, b) =>
              b.created_at.localeCompare(a.created_at)
            )
          );
        }
      } catch (err) {
        console.error("Failed to load file history", err);
        if (!cancelled) {
          setError(`${t("historyLoadFailed")}: ${formatApiError(err)}`);
        }
      }
      if (!cancelled) setLoading(false);
    })();
    return () => {
      cancelled = true;
    };
  }, [file.path, fetchHistory, t]);

  return { events, error, loading };
}

function ProvenanceStrip({
  file,
  fetchHistory,
}: {
  file: BrowsedFile;
  fetchHistory: FetchHistoryFn;
}) {
  const t = useTranslations("FilesPage");
  const format = useFormatter();
  const { events, error, loading } = useProvenance(file, fetchHistory);
  const [expanded, setExpanded] = useState(false);

  const describe = (event: ArtifactEvent) => {
    const actionKey = ACTION_KEYS[event.action];
    const isAgent = event.actor_type === "agent";
    const resolvedActorName = event.actor_display_name?.trim();
    const actorName =
      resolvedActorName && !UUID_PATTERN.test(resolvedActorName)
        ? resolvedActorName
        : !isAgent && !UUID_PATTERN.test(event.created_by)
          ? event.created_by
          : null;
    return t("changeBy", {
      action: actionKey ? t(actionKey) : event.action,
      actor: isAgent
        ? actorName
          ? t("agentActor", { id: actorName })
          : t("unnamedAgent")
        : actorName || t("unknownActor"),
    });
  };
  const when = (iso: string) => {
    const date = parseUtcTimestamp(iso);
    return date ? format.relativeTime(date) : iso;
  };

  if (loading) {
    return (
      <div className="flex shrink-0 items-center gap-2 border-b px-3 py-1.5 text-xs text-muted-foreground">
        <Loader2 className="h-3.5 w-3.5 animate-spin" />
        {t("historyLoading")}
      </div>
    );
  }

  if (error) {
    return (
      <div className="shrink-0 border-b p-2">
        <FormError>{error}</FormError>
      </div>
    );
  }

  const latest = events?.[0];
  if (!latest) {
    return (
      <div className="flex shrink-0 items-center gap-2 border-b px-3 py-1.5 text-xs text-muted-foreground">
        <History className="h-3.5 w-3.5" />
        {t("historyEmpty")}
      </div>
    );
  }

  const Icon = latest.actor_type === "agent" ? Bot : User;
  return (
    <div className="shrink-0 border-b">
      <button
        type="button"
        onClick={() => setExpanded(!expanded)}
        aria-expanded={expanded}
        className="flex w-full items-center gap-2 px-3 py-1.5 text-left text-xs text-muted-foreground hover:bg-muted/50"
      >
        <Icon className="h-3.5 w-3.5 shrink-0" />
        <span className="min-w-0 flex-1 truncate">
          {describe(latest)} · {when(latest.created_at)}
        </span>
        {events.length > 1 && (
          <span className="shrink-0 tabular-nums">{events.length}</span>
        )}
        <ChevronDown
          className={cn(
            "h-3.5 w-3.5 shrink-0 transition-transform",
            expanded && "rotate-180"
          )}
        />
      </button>
      {expanded && (
        <ul className="max-h-48 overflow-auto border-t px-3 py-2 text-xs">
          {events.map((event, index) => (
            <li
              key={`${event.created_at}-${index}`}
              className="flex items-start gap-2 py-1"
            >
              {event.actor_type === "agent" ? (
                <Bot className="mt-0.5 h-3.5 w-3.5 shrink-0 text-muted-foreground" />
              ) : (
                <User className="mt-0.5 h-3.5 w-3.5 shrink-0 text-muted-foreground" />
              )}
              <div className="flex min-w-0 flex-col leading-tight">
                <span className="text-foreground">{describe(event)}</span>
                <span className="text-[11px] text-muted-foreground">
                  {format.dateTime(new Date(event.created_at), {
                    dateStyle: "medium",
                    timeStyle: "short",
                  })}
                  {event.task_id
                    ? ` · ${t("fromTask", { id: event.task_id })}`
                    : ""}
                </span>
              </div>
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}

/**
 * Copy a text file's contents. The icon answers for a moment: a tick when it
 * worked, a cross (and the reason in its label) when the clipboard refused.
 */
function CopyContentsButton({ text }: { text: string }) {
  const t = useTranslations("FilesPage");
  const tCommon = useTranslations("Common");
  const [outcome, setOutcome] = useState<"copied" | "failed" | null>(null);

  const copy = async () => {
    try {
      await navigator.clipboard.writeText(text);
      setOutcome("copied");
    } catch (err) {
      console.error("Failed to copy file contents", err);
      setOutcome("failed");
    }
    setTimeout(() => setOutcome(null), 2000);
  };

  const label =
    outcome === "copied"
      ? t("copied")
      : outcome === "failed"
        ? tCommon("copyFailed")
        : t("copyContents");

  return (
    <Button
      size="icon"
      variant="ghost"
      className="h-7 w-7 shrink-0 text-muted-foreground"
      aria-label={label}
      title={label}
      onClick={() => void copy()}
    >
      {outcome === "copied" ? (
        <Check className="h-4 w-4" />
      ) : outcome === "failed" ? (
        <CircleX className="h-4 w-4 text-destructive" />
      ) : (
        <Copy className="h-4 w-4" />
      )}
    </Button>
  );
}

/**
 * One open file: where it is and what it is above, then its preview. Closing
 * belongs to its tab, which already carries the cross.
 */
export function FileViewerContent({
  file,
  fetchUrl,
  fetchHistory,
  onDelete,
}: {
  file: BrowsedFile;
  fetchUrl: FetchUrlFn;
  fetchHistory?: FetchHistoryFn;
  onDelete?: (file: BrowsedFile) => void;
}) {
  const t = useTranslations("FilesPage");
  const [resolvedUrl, setResolvedUrl] = useState<{
    path: string;
    url: string;
  } | null>(null);
  const [kind, setKind] = useState<ViewerKind | null>(null);
  const [text, setText] = useState<string | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let cancelled = false;
    setResolvedUrl(null);
    setKind(null);
    setText(null);
    setError(null);
    setLoading(true);

    (async () => {
      let href: string;
      try {
        const result = await fetchUrl(file.path);
        if (cancelled) return;
        if (result.error || !result.data) {
          setError(apiErrorMessage(result, t("fileLoadFailed")));
          setLoading(false);
          return;
        }
        href = result.data;
      } catch (err) {
        console.error("Failed to resolve file URL", err);
        if (!cancelled) {
          setError(`${t("fileLoadFailed")}: ${formatApiError(err)}`);
          setLoading(false);
        }
        return;
      }
      setResolvedUrl({ path: file.path, url: href });

      // A picture or a PDF cannot also be source code, so those two are taken
      // at their word and never fetched here — the element does that itself.
      // Everything else is decided by looking, because a missing or wrong
      // content type is the common case rather than the exception.
      const declared = file.content_type ?? null;
      const shortcut = mediaKind(declared);
      if (shortcut === "image" || shortcut === "pdf") {
        setKind(shortcut);
        setLoading(false);
        return;
      }

      try {
        const response = await fetch(href);
        if (!response.ok) throw new Error(`HTTP ${response.status}`);
        const seen = await inspect(
          response,
          declared ?? response.headers.get("content-type")
        );
        if (cancelled) return;
        setKind(seen.kind);
        setText(seen.text);
      } catch (err) {
        console.error("Failed to read file", err);
        if (!cancelled) {
          setError(`${t("readFileFailed")}: ${formatApiError(err)}`);
        }
      }
      if (!cancelled) setLoading(false);
    })();

    return () => {
      cancelled = true;
    };
  }, [file, fetchUrl, t]);
  const url = resolvedUrl?.path === file.path ? resolvedUrl.url : null;

  const fileName = file.path.split("/").pop() || file.path;
  // The folders above it, for a file opened from deep in the tree.
  const folders = file.path.split("/").slice(0, -1).filter(Boolean);
  const extension = fileName.includes(".")
    ? fileName.split(".").pop()?.toUpperCase()
    : undefined;
  const meta = [
    typeof file.size === "number" ? formatFileSize(file.size) : null,
    extension,
  ]
    .filter(Boolean)
    .join(" · ");

  const handleDownload = () => {
    if (!url) return;
    const a = document.createElement("a");
    a.href = url;
    a.download = fileName;
    a.click();
  };

  return (
    <div className="flex h-full min-h-0 w-full flex-col">
      <div className="flex shrink-0 items-center gap-2 border-b px-3 py-2">
        <FileText className="h-4 w-4 shrink-0 text-muted-foreground" />
        <span className="min-w-0 flex-1 truncate text-sm" title={file.path}>
          {folders.length > 0 && (
            <span className="text-muted-foreground">
              {folders.join(" / ")} /{" "}
            </span>
          )}
          {fileName}
        </span>
        {meta && (
          <span className="shrink-0 text-xs tabular-nums text-muted-foreground max-sm:hidden">
            {meta}
          </span>
        )}
        {kind === "text" && text !== null && <CopyContentsButton text={text} />}
        <Button
          size="icon"
          variant="ghost"
          className="h-7 w-7 shrink-0 text-muted-foreground"
          aria-label={t("download")}
          disabled={!url}
          onClick={handleDownload}
        >
          <Download className="h-4 w-4" />
        </Button>
        {onDelete && (
          <Button
            size="icon"
            variant="ghost"
            className="h-7 w-7 shrink-0 text-muted-foreground hover:text-destructive"
            aria-label={t("deleteFile", { name: fileName })}
            onClick={() => onDelete(file)}
          >
            <Trash2 className="h-4 w-4" />
          </Button>
        )}
      </div>

      {url && fetchHistory && (
        <ProvenanceStrip file={file} fetchHistory={fetchHistory} />
      )}

      <div className="min-h-0 flex-1 overflow-auto bg-muted/20">
        {loading && (
          <div className="flex h-full items-center justify-center">
            <Loader2 className="h-5 w-5 animate-spin text-muted-foreground" />
          </div>
        )}

        {!loading && error && (
          <div className="flex h-full items-center justify-center text-sm text-destructive">
            {error}
          </div>
        )}

        {!loading && !error && url && kind === "image" && (
          <div className="flex h-full items-center justify-center p-4">
            <MediaPreview
              kind="image"
              url={url}
              name={fileName}
              className="max-h-full max-w-full"
            />
          </div>
        )}

        {!loading && !error && url && kind === "pdf" && (
          <iframe
            src={url}
            title={fileName}
            className="h-full w-full border-0"
          />
        )}

        {!loading && !error && url && kind === "video" && (
          <div className="flex h-full items-center justify-center p-4">
            <MediaPreview
              kind="video"
              url={url}
              name={fileName}
              className="max-h-full max-w-full"
            />
          </div>
        )}

        {!loading && !error && url && kind === "audio" && (
          <div className="flex h-full items-center justify-center p-8">
            <MediaPreview
              kind="audio"
              url={url}
              name={fileName}
              className="w-full"
            />
          </div>
        )}

        {!loading && !error && kind === "text" && text !== null && (
          <TextPreview path={file.path} text={text} />
        )}

        {!loading && !error && kind === "binary" && (
          <div className="flex h-full flex-col items-center justify-center gap-3 text-sm text-muted-foreground">
            <span>{t("noPreview")}</span>
            <Button size="sm" variant="outline" onClick={handleDownload}>
              <Download className="mr-1.5" />
              {t("download")}
            </Button>
          </div>
        )}
      </div>
    </div>
  );
}
