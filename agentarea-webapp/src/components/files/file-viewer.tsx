"use client";

import { useEffect, useState } from "react";
import { Bot, Download, Loader2, User } from "lucide-react";
import { Button } from "@/components/ui/button";
import type { BrowsedFile } from "./file-tree";

const TEXT_EXTS = new Set([
  "txt",
  "md",
  "json",
  "yaml",
  "yml",
  "csv",
  "log",
  "py",
  "js",
  "jsx",
  "ts",
  "tsx",
  "go",
  "rs",
  "html",
  "css",
  "sh",
  "toml",
  "ini",
  "xml",
  "sql",
]);

const IMAGE_EXTS = new Set(["png", "jpg", "jpeg", "gif", "webp", "svg", "bmp", "ico"]);

type ViewerKind = "image" | "pdf" | "text" | "video" | "audio" | "binary";

function classify(file: BrowsedFile): ViewerKind {
  const ext = file.path.split(".").pop()?.toLowerCase() || "";
  const ct = (file.content_type || "").toLowerCase();
  if (ct.startsWith("image/") || IMAGE_EXTS.has(ext)) return "image";
  if (ct === "application/pdf" || ext === "pdf") return "pdf";
  if (ct.startsWith("video/") || ["mp4", "webm", "mov"].includes(ext)) return "video";
  if (ct.startsWith("audio/") || ["mp3", "wav", "ogg", "m4a"].includes(ext)) return "audio";
  if (ct.startsWith("text/") || ct.includes("json") || ct.includes("xml") || TEXT_EXTS.has(ext)) {
    return "text";
  }
  return "binary";
}

export type FetchUrlFn = (path: string) => Promise<string | null>;

export type ArtifactEvent = {
  action: string;
  actor_type: string;
  created_by: string;
  agent_id?: string | null;
  task_id?: string | null;
  created_at: string;
};

export type FetchHistoryFn = (path: string) => Promise<ArtifactEvent[]>;

const ACTION_LABELS: Record<string, string> = {
  created: "added",
  modified: "modified",
  deleted: "deleted",
};

function formatTimestamp(iso: string): string {
  const d = new Date(iso);
  if (Number.isNaN(d.getTime())) return iso;
  return d.toLocaleString();
}

function ProvenanceRow({ event }: { event: ArtifactEvent }) {
  const isAgent = event.actor_type === "agent";
  const Icon = isAgent ? Bot : User;
  const actorLabel = isAgent
    ? `Agent ${event.agent_id ?? "?"}`
    : event.created_by || "Unknown user";
  return (
    <li className="flex items-start gap-2 py-1">
      <Icon className="mt-0.5 h-3.5 w-3.5 shrink-0 text-muted-foreground" />
      <div className="flex flex-col leading-tight">
        <span className="text-foreground">
          {actorLabel} {ACTION_LABELS[event.action] ?? event.action} this file
        </span>
        <span className="text-[11px] text-muted-foreground">
          {formatTimestamp(event.created_at)}
          {isAgent && event.task_id ? ` · task ${event.task_id}` : ""}
        </span>
      </div>
    </li>
  );
}

function ProvenancePanel({
  file,
  fetchHistory,
}: {
  file: BrowsedFile;
  fetchHistory: FetchHistoryFn;
}) {
  const [events, setEvents] = useState<ArtifactEvent[] | null>(null);
  const [loading, setLoading] = useState(false);

  useEffect(() => {
    let cancelled = false;
    setEvents(null);
    setLoading(true);
    (async () => {
      const result = await fetchHistory(file.path).catch(() => []);
      if (!cancelled) {
        setEvents(result);
        setLoading(false);
      }
    })();
    return () => {
      cancelled = true;
    };
  }, [file, fetchHistory]);

  if (loading) {
    return (
      <div className="flex items-center gap-2 border-b px-3 py-2 text-xs text-muted-foreground">
        <Loader2 className="h-3.5 w-3.5 animate-spin" />
        Loading history…
      </div>
    );
  }

  if (!events || events.length === 0) {
    return (
      <div className="border-b px-3 py-2 text-xs text-muted-foreground">
        No history recorded for this file yet.
      </div>
    );
  }

  return (
    <div className="border-b px-3 py-2">
      <ul className="text-xs">
        {events.map((ev, i) => (
          <ProvenanceRow key={`${ev.created_at}-${i}`} event={ev} />
        ))}
      </ul>
    </div>
  );
}

export function FileViewerContent({
  file,
  fetchUrl,
  fetchHistory,
}: {
  file: BrowsedFile;
  fetchUrl: FetchUrlFn;
  fetchHistory?: FetchHistoryFn;
}) {
  const [url, setUrl] = useState<string | null>(null);
  const [text, setText] = useState<string | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let cancelled = false;
    setUrl(null);
    setText(null);
    setError(null);

    const kind = classify(file);
    setLoading(true);

    (async () => {
      const presigned = await fetchUrl(file.path).catch(() => null);
      if (cancelled) return;
      if (!presigned) {
        setError("Failed to load file");
        setLoading(false);
        return;
      }
      setUrl(presigned);

      if (kind === "text") {
        try {
          const resp = await fetch(presigned);
          const body = await resp.text();
          if (!cancelled) setText(body);
        } catch {
          if (!cancelled) setError("Failed to read file contents");
        }
      }
      if (!cancelled) setLoading(false);
    })();

    return () => {
      cancelled = true;
    };
  }, [file, fetchUrl]);

  const kind = classify(file);
  const fileName = file.path.split("/").pop() || file.path;

  const handleDownload = () => {
    if (!url) return;
    const a = document.createElement("a");
    a.href = url;
    a.download = fileName;
    a.click();
  };

  return (
    <div className="flex h-full flex-col">
      <div className="border-b px-3 py-2">
        <span className="truncate text-xs text-muted-foreground" title={file.path}>
          {file.path}
        </span>
      </div>

      {fetchHistory && <ProvenancePanel file={file} fetchHistory={fetchHistory} />}

      <div className="flex-1 overflow-auto bg-muted/20">
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
            {/* eslint-disable-next-line @next/next/no-img-element */}
            <img src={url} alt={fileName} className="max-h-full max-w-full object-contain" />
          </div>
        )}

        {!loading && !error && url && kind === "pdf" && (
          <iframe src={url} title={fileName} className="h-full w-full border-0" />
        )}

        {!loading && !error && url && kind === "video" && (
          <div className="flex h-full items-center justify-center p-4">
            <video src={url} controls className="max-h-full max-w-full" />
          </div>
        )}

        {!loading && !error && url && kind === "audio" && (
          <div className="flex h-full items-center justify-center p-8">
            <audio src={url} controls className="w-full" />
          </div>
        )}

        {!loading && !error && kind === "text" && text !== null && (
          <pre className="whitespace-pre-wrap break-words p-4 text-xs font-mono">
            {text}
          </pre>
        )}

        {!loading && !error && kind === "binary" && (
          <div className="flex h-full flex-col items-center justify-center gap-3 text-sm text-muted-foreground">
            <span>Preview not available for this file type.</span>
            <Button size="sm" variant="outline" onClick={handleDownload}>
              <Download className="mr-1.5 h-3.5 w-3.5" />
              Download
            </Button>
          </div>
        )}
      </div>
    </div>
  );
}
