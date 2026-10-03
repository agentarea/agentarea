"use client";

import { useMemo, useSyncExternalStore } from "react";
import { Streamdown } from "streamdown";
import { useWorkspaceSlug } from "@/hooks/useWorkspaceNavigation";
import { cn } from "@/lib/utils";
import styles from "./MessageMarkdown.module.css";
import {
  fileAwareMarkdownComponents,
  preprocessFileLinks,
} from "./utils/markdownComponents";
import {
  type BrowserImageSources,
  messageRehypePlugins,
} from "./utils/markdownImagePolicy";

const noopSubscribe = () => () => {};

let browserImageSources: BrowserImageSources | undefined;

// useSyncExternalStore needs the same object on every read.
function readBrowserImageSources(): BrowserImageSources {
  browserImageSources ??= {
    appOrigin: window.location.origin,
    apiUrl:
      (window as Window & { __ENV__?: { CLIENT_API_URL?: string } }).__ENV__
        ?.CLIENT_API_URL || null,
  };
  return browserImageSources;
}

export interface MessageMarkdownProps {
  children?: string;
  className?: string;
  content?: string;
  isStreaming?: boolean;
}

/** Shared Markdown presentation for assistant prose and textual tool output. */
export function MessageMarkdown({
  children,
  className,
  content,
  isStreaming = false,
}: MessageMarkdownProps) {
  const markdown = content ?? children ?? "";
  // Null while server rendering and hydrating, so both decide images alike.
  const imageSources = useSyncExternalStore(
    noopSubscribe,
    readBrowserImageSources,
    () => null
  );
  const workspaceSlug = useWorkspaceSlug();
  const rehypePlugins = useMemo(
    () => messageRehypePlugins(imageSources, workspaceSlug),
    [imageSources, workspaceSlug]
  );

  return (
    <Streamdown
      className={cn(styles.root, className)}
      components={fileAwareMarkdownComponents}
      rehypePlugins={rehypePlugins}
      isAnimating={isStreaming}
      linkSafety={{ enabled: false }}
      mode={isStreaming ? "streaming" : "static"}
      parseIncompleteMarkdown={isStreaming}
    >
      {preprocessFileLinks(markdown)}
    </Streamdown>
  );
}

export default MessageMarkdown;
