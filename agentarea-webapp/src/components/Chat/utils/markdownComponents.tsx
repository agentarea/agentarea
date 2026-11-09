import React from "react";
import type { Components, ExtraProps } from "streamdown";
import {
  useTaskFileLink,
  useTaskFileOpen,
} from "@/lib/events/parts/TaskFileUrl";
import { fileBasename, FileChip, isFileLike } from "./fileIcon";
import { SiteLink } from "./SiteLink";

/**
 * Rewrite markdown file-links whose target is NOT a real web URL
 * (e.g. `[leads_raw.csv](sandbox:/x)`) into inline code `` `leads_raw.csv` ``.
 * rehype-harden renders such links as "[blocked]"; converting them to inline
 * code sidesteps that entirely, and our `inlineCode` renderer turns them into
 * file chips. Real http(s) file-links are left intact (handled by the `a`
 * renderer, which keeps them clickable).
 */
export function preprocessFileLinks(md: string): string {
  if (!md) return md;
  return md.replace(/\[([^\]]+)\]\(([^)\s]+)\)/g, (full, text, url) => {
    // A path relative to the task's folder gets a marker path, which survives
    // sanitize and harden (that one makes relative links absolute on the app's
    // origin); the `a` renderer turns it into the task's file URL.
    if (isTaskRelative(url) && (isFileLike(text) || isFileLike(url))) {
      return `[${text}](${TASK_FILE_PATH}${url})`;
    }
    // Keep real, reachable links (web URLs and same-origin API paths); only
    // unreachable schemes (sandbox:/file:/…) get downgraded to a plain chip.
    const reachable = /^(https?:\/\/|\/)/i.test(url);
    if (!reachable && (isFileLike(text) || isFileLike(url))) {
      const name = isFileLike(text) ? text : fileBasename(url);
      return "`" + name + "`";
    }
    return full;
  });
}

/** A link to a file in the task's own folder: no scheme, not rooted, not an anchor. */
function isTaskRelative(href: string): boolean {
  return href !== "" && !/^([a-z][a-z0-9+.-]*:|\/|#)/i.test(href);
}

const TASK_FILE_PATH = "/__task-file/";

/** The task-folder path a marked link points at, or null for any other link. */
function taskFilePath(href: string): string | null {
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

/** Flatten a React children tree into its text content. */
function childText(children: React.ReactNode): string {
  if (children == null || typeof children === "boolean") return "";
  if (typeof children === "string" || typeof children === "number")
    return String(children);
  if (Array.isArray(children)) return children.map(childText).join("");
  if (React.isValidElement(children)) {
    return childText(
      (children.props as { children?: React.ReactNode }).children
    );
  }
  return "";
}

/**
 * Streamdown/markdown component overrides shared across assistant messages and
 * tool results:
 * - links to files (leads_raw.csv, report.docx, …) render as a file chip with a
 *   type-specific icon and a clickable name
 * - other external links get a small globe so result lists read like link lists
 * - preserves the existing <think> styling
 */
export const fileAwareMarkdownComponents: Components = {
  think: (props: Record<string, unknown>) => (
    <div className="text-xs text-gray-400 dark:text-gray-300">
      {props.children as React.ReactNode}
    </div>
  ),
  // Inline code that is just a filename (`leads_raw.csv`) → render as a file chip.
  // Streamdown routes only inline code here; fenced blocks keep their renderer.
  inlineCode: ({
    children,
    node: _node,
    ...props
  }: React.ComponentProps<"code"> & ExtraProps) => {
    void _node;
    const text = childText(children);
    if (isFileLike(text)) {
      return <FileChip name={text} />;
    }
    return (
      <code
        className="rounded bg-muted px-1 py-0.5 font-mono text-[0.85em]"
        {...props}
      >
        {children}
      </code>
    );
  },
  a: function MarkdownLink({
    href,
    children,
  }: React.ComponentProps<"a"> & ExtraProps) {
    const taskFileLink = useTaskFileLink();
    const openTaskFile = useTaskFileOpen();
    const taskPath = typeof href === "string" ? taskFilePath(href) : null;
    // Inside a task a link to its folder opens the file in the task's Files
    // tab; real web URLs stay clickable; sandbox:/file: and other schemes would
    // otherwise render as dead/"blocked" links.
    const reachableHref =
      taskPath !== null
        ? (taskFileLink?.(taskPath) ?? undefined)
        : typeof href === "string" && /^(https?:\/\/|\/)/.test(href)
          ? href
          : undefined;
    const text = childText(children);

    if (isFileLike(text) || isFileLike(href) || taskPath !== null) {
      const iconName = isFileLike(text) ? text : (taskPath ?? href ?? "");
      const name = text || fileBasename(iconName);
      return (
        <FileChip
          name={name}
          iconName={iconName}
          href={reachableHref}
          newTab={taskPath === null}
          onOpen={
            taskPath !== null && openTaskFile
              ? () => openTaskFile(taskPath)
              : undefined
          }
        />
      );
    }

    if (!reachableHref) {
      // Non-web link with no file name — just render its text, no broken anchor.
      return <span>{children}</span>;
    }

    return <SiteLink href={reachableHref}>{children}</SiteLink>;
  },
};

export default fileAwareMarkdownComponents;
