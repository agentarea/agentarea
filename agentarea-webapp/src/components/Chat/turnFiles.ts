import type { CompletedRun } from "@/lib/events/reducer";
import { parseUtcTimestamp } from "@/utils/dateUtils";
import type { ActivitySegment } from "./activityView";

/** The fields of a published task file these helpers read. */
export interface PublishedFile {
  path: string;
  created_at: string | null;
}

// The file store stamps a file by its own clock, the run's end by the platform's.
const CLOCK_SLACK_MS = 5_000;

const PREVIEW_IMAGE = /\.(png|jpe?g|webp|gif)$/i;

/** Whether a path names a picture the transcript shows in place. */
export function isPreviewableImage(path: string): boolean {
  return PREVIEW_IMAGE.test(path.split(/[?#]/)[0]);
}

/** A link to a file in the task's own folder: no scheme, not rooted, not an anchor. */
export function isTaskRelative(href: string): boolean {
  return href !== "" && !/^([a-z][a-z0-9+.-]*:|\/|#)/i.test(href);
}

/** The marker path a task-relative link is rewritten to, so it survives sanitize. */
export const TASK_FILE_PATH = "/__task-file/";

/** The task-folder path a marked link points at, or null for any other link. */
export function taskFilePath(href: string): string | null {
  try {
    const { pathname } = new URL(href, "http://task.invalid");
    return pathname.startsWith(TASK_FILE_PATH)
      ? decodePath(pathname.slice(TASK_FILE_PATH.length))
      : null;
  } catch {
    return null;
  }
}

function decodePath(href: string): string {
  try {
    return decodeURIComponent(href);
  } catch {
    return href;
  }
}

const MARKDOWN_LINK = /\[([^\]]+)\]\(([^)\s]+)\)/g;

/** The task files a message links to, as task paths. */
export function linkedTaskFiles(markdown: string): Set<string> {
  const paths = new Set<string>();
  for (const [, , url] of markdown.matchAll(MARKDOWN_LINK)) {
    if (!isTaskRelative(url)) continue;
    const path = taskFilePath(`${TASK_FILE_PATH}${url}`);
    if (path) paths.add(path);
  }
  return paths;
}

function timeOf(value: string | null | undefined): number | null {
  return parseUtcTimestamp(value)?.getTime() ?? null;
}

/**
 * The files each completed run published, by run id: what the store first
 * stamped after the run before it ended and by the time this one did. A file
 * published again unchanged keeps its first stamp, so it stays with the run
 * that made it; of several versions of one path, a run shows its latest.
 */
export function publishedByRun<T extends PublishedFile>(
  files: T[],
  runs: CompletedRun[]
): Map<string, T[]> {
  const byRun = new Map<string, T[]>();
  let after = -Infinity;
  for (const run of runs) {
    const ended = timeOf(run.endedAt);
    if (ended === null) continue;
    const until = ended + CLOCK_SLACK_MS;
    const latest = new Map<string, { file: T; at: number }>();
    for (const file of files) {
      const at = timeOf(file.created_at);
      if (at === null || at <= after || at > until) continue;
      const seen = latest.get(file.path);
      if (!seen || at > seen.at) latest.set(file.path, { file, at });
    }
    if (latest.size > 0) {
      byRun.set(
        run.id,
        [...latest.values()]
          .map(({ file }) => file)
          .sort((a, b) => a.path.localeCompare(b.path))
      );
    }
    after = until;
  }
  return byRun;
}

/**
 * The version of a path the task had published by `endedAt` (a run's end),
 * or its latest version without one; null when there is none.
 */
export function publishedFile<T extends PublishedFile>(
  files: T[],
  path: string,
  endedAt?: string | null
): T | null {
  const ended = endedAt === undefined ? null : timeOf(endedAt);
  if (endedAt !== undefined && ended === null) return null;
  let best: { file: T; at: number } | null = null;
  for (const file of files) {
    if (file.path !== path) continue;
    const at = timeOf(file.created_at) ?? -Infinity;
    if (ended !== null && at > ended + CLOCK_SLACK_MS) continue;
    if (!best || at > best.at) best = { file, at };
  }
  return best?.file ?? null;
}

/** The completed run each segment belongs to; null for live work. */
export function segmentRuns(
  segments: ActivitySegment[],
  runs: CompletedRun[]
): (CompletedRun | null)[] {
  const byPart = new Map<string, CompletedRun>();
  for (const run of runs) {
    for (const id of run.partIds) byPart.set(id, run);
    // An answer the run's parts did not hold is synthesized under this id.
    byPart.set(`${run.id}-answer`, run);
  }
  return segments.map((segment) => {
    const ids =
      segment.kind === "work"
        ? segment.run.parts.map((part) => part.partId)
        : [segment.part.partId];
    for (const id of ids) {
      const run = byPart.get(id);
      if (run) return run;
    }
    return null;
  });
}

/** The index of each run's last segment, where its files go: its answer when it has one. */
export function runEnds(owners: (CompletedRun | null)[]): Set<number> {
  const last = new Map<string, number>();
  owners.forEach((run, index) => {
    if (run) last.set(run.id, index);
  });
  return new Set(last.values());
}
