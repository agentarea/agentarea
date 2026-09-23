import React from "react";
import { renderToStaticMarkup } from "react-dom/server";
import { afterAll, beforeAll, describe, expect, it, vi } from "vitest";
import { FileBrowser } from "./file-browser";

vi.mock("next-intl", () => ({
  useTranslations: () => (key: string) => key,
  useFormatter: () => ({ dateTime: () => "date", relativeTime: () => "ago" }),
}));

beforeAll(() => vi.stubGlobal("React", React));
afterAll(() => vi.unstubAllGlobals());

const files = [
  { path: "docs/a.md", size: 10, content_type: "text/markdown" },
  { path: "docs/b.md", size: 20 },
  { path: "docs/c.md", size: 30 },
];

function panels(active: string | null) {
  const markup = renderToStaticMarkup(
    <FileBrowser
      files={files}
      state={{
        folder: "docs",
        tabs: { open: files.map((file) => file.path), active },
      }}
      onChange={() => {}}
      fetchUrl={async () => null}
    />
  );
  return Array.from(markup.matchAll(/role="tabpanel"[^>]*/g)).map((match) => {
    const tag = match[0];
    return {
      id: /id="([^"]*)"/.exec(tag)?.[1] ?? "",
      classes: (/class="([^"]*)"/.exec(tag)?.[1] ?? "").split(" "),
    };
  });
}

describe("browser panes", () => {
  // Radix keeps an empty div for every tab it has shown and marks it with the
  // `hidden` attribute — which a `flex` class silently outranks in Tailwind's
  // cascade. Left that way, each stale panel stays visible and `flex-1` hands
  // it an equal share of the height, pushing the open file down the screen.
  it("lays out only the pane on screen, whichever tab that is", () => {
    for (const active of [null, "docs/a.md", "docs/c.md"]) {
      const laidOut = panels(active).filter(
        (panel) => !panel.classes.includes("hidden")
      );
      expect(laidOut).toHaveLength(1);
      expect(laidOut[0].id).toContain(active ?? "content-.");
      expect(laidOut[0].classes).toContain("flex");
    }
  });

  it("never gives a hidden pane a display class that would show it", () => {
    for (const panel of panels("docs/c.md")) {
      if (!panel.classes.includes("hidden")) continue;
      expect(panel.classes).not.toContain("flex");
    }
  });
});
