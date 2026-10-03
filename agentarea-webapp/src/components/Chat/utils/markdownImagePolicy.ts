import type { harden as rehypeHarden } from "rehype-harden";
import { defaultRehypePlugins, type StreamdownProps } from "streamdown";

type RehypePlugins = NonNullable<StreamdownProps["rehypePlugins"]>;
type Plugin = Extract<RehypePlugins[number], (...args: never[]) => unknown>;
type HardenOptions = Parameters<typeof rehypeHarden>[0];

const defaultHarden = defaultRehypePlugins.harden;
if (
  !Array.isArray(defaultHarden) ||
  typeof defaultHarden[0] !== "function" ||
  typeof defaultHarden[1] !== "object" ||
  defaultHarden[1] === null
) {
  throw new TypeError("Streamdown harden defaults do not expose an options tuple");
}
const hardenPlugin: Plugin = defaultHarden[0];
const hardenDefaults: HardenOptions = defaultHarden[1];

/** Where the browser rendering chat Markdown is and which API it talks to. */
export interface BrowserImageSources {
  /** Origin of the page; relative image paths resolve against it. */
  appOrigin: string;
  /** Public API base URL, or null when the page was not given one. */
  apiUrl: string | null;
}

interface HastNode {
  type: string;
  tagName?: string;
  properties?: Record<string, unknown>;
  children?: HastNode[];
}

/**
 * The only places chat Markdown may load images from: the current
 * workspace's file downloads, through the webapp proxy or straight from the
 * API. Whole origins are not trusted: both serve redirects (the proxy follows
 * whatever the API answers, the API's /oauth2/auth hands any query to Hydra),
 * and an image load that follows one carries prompt-injected data off-site.
 */
export function workspaceFileImagePrefixes(
  sources: BrowserImageSources,
  workspaceSlug: string | null
): string[] {
  if (!workspaceSlug) return [];
  const filesPath = `/v1/workspaces/${encodeURIComponent(workspaceSlug)}/files/download/`;
  const prefixes = [`${sources.appOrigin}/api/proxy${filesPath}`];
  const apiBase = apiBaseUrl(sources.apiUrl);
  if (apiBase) prefixes.push(`${apiBase}${filesPath}`);
  return prefixes;
}

function apiBaseUrl(apiUrl: string | null): string | null {
  if (!apiUrl) return null;
  try {
    const url = new URL(apiUrl);
    return `${url.origin}${url.pathname.replace(/\/+$/, "")}`;
  } catch {
    return null;
  }
}

/**
 * rehype-harden checks only `<img src>`. Sanitize keeps `<picture>` with
 * `<source srcset>`, and the browser loads a source's srcset instead of the
 * vetted img, so sources are dropped and pictures unwrapped to their img.
 */
export function stripResponsiveImageSources() {
  return (tree: HastNode) => {
    stripSources(tree);
  };
}

function stripSources(parent: HastNode): void {
  if (!parent.children) return;
  parent.children = parent.children.flatMap((child) => {
    if (child.type !== "element") return [child];
    if (child.tagName === "source") return [];
    if (child.properties) {
      delete child.properties.srcSet;
      delete child.properties.srcset;
    }
    stripSources(child);
    return child.tagName === "picture" ? (child.children ?? []) : [child];
  });
}

/**
 * Rehype plugins for chat Markdown. `sources` is null wherever the browser
 * is not known yet — server rendering and hydration — and then no remote
 * image is allowed, so both render the same markup; blocked images show
 * their alt text until the browser re-renders with its own sources.
 */
export function messageRehypePlugins(
  sources: BrowserImageSources | null,
  workspaceSlug: string | null
): RehypePlugins {
  const harden: HardenOptions = sources
    ? {
        ...hardenDefaults,
        defaultOrigin: sources.appOrigin,
        allowedImagePrefixes: workspaceFileImagePrefixes(sources, workspaceSlug),
        allowDataImages: true,
      }
    : {
        ...hardenDefaults,
        allowedImagePrefixes: [],
        allowDataImages: true,
        imageBlockPolicy: "text-only",
      };
  return [
    defaultRehypePlugins.raw,
    defaultRehypePlugins.sanitize,
    [hardenPlugin, harden],
    stripResponsiveImageSources,
  ];
}
