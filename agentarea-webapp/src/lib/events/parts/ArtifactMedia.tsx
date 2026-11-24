"use client";

import { useEffect, useState, type ReactNode } from "react";
import { FileChip, getFileMeta } from "@/components/Chat/utils/fileIcon";
import { sniffMedia, type MediaKind } from "@/components/files/content-sniff";
import { MediaPreview } from "@/components/files/file-viewer";
import { isSameOriginPath } from "@/lib/same-origin-path";
import { cn } from "@/lib/utils";
import { useTaskFileUrl } from "./TaskFileUrl";

const MEDIA_TYPES = new Set(["Image", "Video"]);

/** A produced file: an image or a video shown inline, anything else a chip. */
export function ArtifactMedia({
  path,
  name,
  href,
  mimeType,
  className,
  inline = false,
  caption,
}: {
  path?: string;
  name?: string;
  href?: string;
  mimeType?: string | null;
  className?: string;
  /** Inside a paragraph: drawn with spans, and the chip alone has no wrapper. */
  inline?: boolean;
  /** Shown under the media in place of the file's own chip. */
  caption?: ReactNode;
}) {
  const taskFileUrl = useTaskFileUrl();
  const label = name ?? path ?? "";
  const url = href ?? (path && taskFileUrl?.(path)) ?? null;
  // Only a file on this site is opened unasked; an agent-chosen host is a link.
  const previewable = !!url && isSameOriginPath(url);
  // The name only decides whether a file is worth opening; the bytes decide
  // what it is. Every script a shell run writes is not fetched to find out.
  const mayBeMedia = MEDIA_TYPES.has(getFileMeta(path ?? label, mimeType).type);
  const [kind, setKind] = useState<MediaKind | null>(null);

  useEffect(() => {
    setKind(null);
    if (!url || !previewable || !mayBeMedia) return;
    const controller = new AbortController();
    (async () => {
      try {
        const response = await fetch(url, { signal: controller.signal });
        // A sandbox that has expired no longer serves the file; the chip stays.
        if (!response.ok) {
          await response.body?.cancel();
          return;
        }
        const seen = await sniffMedia(
          response,
          mimeType ?? response.headers.get("content-type")
        );
        if (!controller.signal.aborted) setKind(seen);
      } catch (err) {
        if (!controller.signal.aborted) {
          console.error("Failed to inspect artifact", err);
        }
      }
    })();
    return () => controller.abort();
  }, [url, mimeType, mayBeMedia, previewable]);

  const chip = caption ?? (
    <FileChip
      name={label}
      iconName={path ?? label}
      mimeType={mimeType ?? undefined}
      href={kind ? (url ?? undefined) : href}
      className="min-w-0"
    />
  );

  if (!url || (kind !== "image" && kind !== "video")) {
    return inline ? (
      chip
    ) : (
      <div className={cn("min-w-0", className)}>{chip}</div>
    );
  }

  // A paragraph cannot hold a figure.
  const Frame = inline ? "span" : "figure";
  const Caption = inline ? "span" : "figcaption";
  return (
    <Frame className={cn("flex min-w-0 flex-col gap-1", className)}>
      {kind === "image" ? (
        <a
          href={url}
          target="_blank"
          rel="noopener noreferrer"
          className="w-fit"
        >
          <MediaPreview
            kind="image"
            url={url}
            name={label}
            className="max-h-64 max-w-full rounded-md border bg-muted/20"
          />
        </a>
      ) : (
        <MediaPreview
          kind="video"
          url={url}
          name={label}
          className="max-h-72 max-w-full rounded-md border bg-black"
        />
      )}
      <Caption className={inline ? undefined : "text-[11px]"}>{chip}</Caption>
    </Frame>
  );
}
