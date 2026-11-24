import { describe, expect, it } from "vitest";
import type { Part } from "@/lib/events/contract";
import type { CompletedRun } from "@/lib/events/reducer";
import { buildActivitySegments } from "./activityView";
import {
  isPreviewableImage,
  linkedTaskFiles,
  publishedByRun,
  publishedFile,
  runEnds,
  segmentRuns,
} from "./turnFiles";

const run = (
  id: string,
  endedAt: string | null,
  partIds: string[] = []
): CompletedRun => ({
  id,
  partIds,
  terminalType: "task.completed",
  terminalMessage: "Task completed.",
  terminalAnswer: null,
  endedAt,
});

const file = (path: string, created_at: string | null, id = path) => ({
  id,
  path,
  created_at,
});

describe("turn files", () => {
  it("previews only the picture formats a browser shows", () => {
    expect(isPreviewableImage("outputs/cat_cosmonaut.png")).toBe(true);
    expect(isPreviewableImage("outputs/photo.JPEG?v=1")).toBe(true);
    expect(isPreviewableImage("outputs/plot.svg")).toBe(false);
    expect(isPreviewableImage("outputs/report.pdf")).toBe(false);
  });

  it("reads the task files a message links to, as task paths", () => {
    expect(
      linkedTaskFiles(
        "Готово: [скачать PNG](outputs/cat_cosmonaut.png), [site](https://x.io/a.png), " +
          "[спец](./outputs/my%20spec.md), [root](/outputs/x.png)"
      )
    ).toEqual(new Set(["outputs/cat_cosmonaut.png", "outputs/my spec.md"]));
  });

  it("gives each run the files first published while it ran", () => {
    const runs = [
      run("run-1", "2026-11-24T10:00:00Z"),
      run("run-2", "2026-11-24T10:05:00Z"),
    ];
    const files = [
      file("outputs/a.png", "2026-11-24T09:59:58Z"),
      // The store's clock runs a little ahead of the platform's.
      file("outputs/b.csv", "2026-11-24T10:00:03Z"),
      file("outputs/a.png", "2026-11-24T10:04:00Z", "a-v2"),
      file("outputs/c.txt", "2026-11-24T10:04:30Z"),
      file("outputs/late.txt", "2026-11-24T10:30:00Z"),
      file("outputs/unstamped.txt", null),
    ];
    const byRun = publishedByRun(files, runs);
    expect(byRun.get("run-1")?.map((f) => f.id)).toEqual([
      "outputs/a.png",
      "outputs/b.csv",
    ]);
    expect(byRun.get("run-2")?.map((f) => f.id)).toEqual([
      "a-v2",
      "outputs/c.txt",
    ]);
  });

  it("keeps a run's latest version of a path it published twice", () => {
    const byRun = publishedByRun(
      [
        file("outputs/a.png", "2026-11-24T09:58:00Z", "old"),
        file("outputs/a.png", "2026-11-24T09:59:00Z", "new"),
      ],
      [run("run-1", "2026-11-24T10:00:00Z")]
    );
    expect(byRun.get("run-1")?.map((f) => f.id)).toEqual(["new"]);
  });

  it("gives nothing to a run whose end is unknown", () => {
    expect(
      publishedByRun(
        [file("outputs/a.png", "2026-11-24T09:59:00Z")],
        [run("run-1", null)]
      ).size
    ).toBe(0);
  });

  it("opens a link as the run that wrote it left the file", () => {
    const files = [
      file("outputs/a.png", "2026-11-24T09:59:00Z", "v1"),
      file("outputs/a.png", "2026-11-24T10:04:00Z", "v2"),
    ];
    expect(
      publishedFile(files, "outputs/a.png", "2026-11-24T10:00:00Z")?.id
    ).toBe("v1");
    expect(publishedFile(files, "outputs/a.png")?.id).toBe("v2");
    expect(
      publishedFile(files, "outputs/a.png", "2026-11-24T09:00:00Z")
    ).toBeNull();
    expect(publishedFile(files, "outputs/b.png")).toBeNull();
  });

  it("puts a run's files after its answer, once", () => {
    const tool: Part = {
      partId: "t1",
      kind: "tool",
      eventType: "tool.result",
      data: { tool_name: "shell", success: true },
    };
    const answer: Part = {
      partId: "a1",
      kind: "llm",
      eventType: "llm.call.completed",
      data: { content: "Готово" },
    };
    const live: Part = {
      partId: "t2",
      kind: "tool",
      eventType: "tool.result",
      data: { tool_name: "shell", success: true },
    };
    const runs = [run("run-1", "2026-11-24T10:00:00Z", ["t1", "a1"])];
    const segments = buildActivitySegments([tool, answer, live], runs);
    const owners = segmentRuns(segments, runs);
    expect(segments.map((s) => s.kind)).toEqual(["work", "answer", "work"]);
    expect(owners.map((r) => r?.id ?? null)).toEqual(["run-1", "run-1", null]);
    expect([...runEnds(owners)]).toEqual([1]);
  });
});
