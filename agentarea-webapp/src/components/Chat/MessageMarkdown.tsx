import { Streamdown } from "streamdown";
import type { Components } from "streamdown";
import { cn } from "@/lib/utils";
import styles from "./MessageMarkdown.module.css";
import {
  fileAwareMarkdownComponents,
  preprocessFileLinks,
} from "./utils/markdownComponents";

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

  return (
    <Streamdown
      className={cn(styles.root, className)}
      components={fileAwareMarkdownComponents as Components}
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
