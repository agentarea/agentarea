import type { harden as rehypeHarden } from "rehype-harden";
import {
  defaultRehypePlugins,
  Streamdown,
  type StreamdownProps,
} from "streamdown";
import { cn } from "@/lib/utils";
import styles from "./MessageMarkdown.module.css";
import {
  fileAwareMarkdownComponents,
  preprocessFileLinks,
} from "./utils/markdownComponents";

type Plugin = Extract<
  NonNullable<StreamdownProps["rehypePlugins"]>[number],
  (...args: never[]) => unknown
>;
type HardenOptions = Parameters<typeof rehypeHarden>[0];
type HardenPlugin = [Plugin, HardenOptions];

const defaultHarden = defaultRehypePlugins.harden;
if (
  !Array.isArray(defaultHarden) ||
  typeof defaultHarden[0] !== "function" ||
  typeof defaultHarden[1] !== "object" ||
  defaultHarden[1] === null
) {
  throw new TypeError("Streamdown harden defaults do not expose an options tuple");
}

function originOfUrl(url: string | undefined): string | null {
  if (!url) return null;
  try {
    return new URL(url).origin;
  } catch {
    return null;
  }
}

const imageOrigin =
  typeof window === "undefined"
    ? originOfUrl(process.env.WEBAPP_PUBLIC_ORIGIN) ?? ""
    : window.location.origin;
const clientApiUrl =
  typeof window === "undefined"
    ? process.env.API_BROWSER_URL || process.env.API_URL
    : (
        window as Window & {
          __ENV__?: { CLIENT_API_URL?: string };
        }
      ).__ENV__?.CLIENT_API_URL;
const apiImageOrigin = originOfUrl(clientApiUrl);
const allowedImagePrefixes = [imageOrigin, apiImageOrigin].filter(
  (origin): origin is string => origin !== null && origin !== ""
);
const hardenPlugin: HardenPlugin = [
  defaultHarden[0],
  {
    ...defaultHarden[1],
    defaultOrigin: imageOrigin,
    allowedImagePrefixes,
    allowDataImages: true,
  },
];
const rehypePlugins: NonNullable<StreamdownProps["rehypePlugins"]> = [
  defaultRehypePlugins.raw,
  defaultRehypePlugins.sanitize,
  hardenPlugin,
];

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
