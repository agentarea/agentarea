import { describe, expect, it } from "vitest";
import type {
  FeedEventResponse,
  ProcessingStatus,
} from "@/api/client/types.gen";
import { applyRecorded } from "./eventFeed";
import {
  feedItems,
  feedStops,
  groupsPlatformRuns,
  isRunExpanded,
  kindBreakdown,
  neighbourStop,
  runHolding,
  worstStatus,
  type FeedItem,
  type PlatformRun,
} from "./eventFeedRuns";

function event(
  sequence: number,
  over: Partial<FeedEventResponse> & { status?: ProcessingStatus } = {}
): FeedEventResponse {
  const { status = "no_handlers", ...rest } = over;
  return {
    sequence,
    v: 1,
    event_id: `e${sequence}`,
    stream_id: "s1",
    source_id: null,
    source_type: "generic_webhook",
    kind: "order.paid",
    key: `k${sequence}`,
    session_key: null,
    sender: null,
    received_at: `2026-10-19T10:${String(sequence).padStart(2, "0")}:00Z`,
    occurred_at: "2026-10-19T10:00:00Z",
    depth: 0,
    correlation_id: null,
    causation_id: null,
    attachments: 0,
    processing: {
      status,
      subscribers: null,
      reacted: 0,
      skipped: 0,
      errors: 0,
      tasks: [],
    },
    ...rest,
  };
}

function platform(
  sequence: number,
  kind = "task.completed",
  status: ProcessingStatus = "skipped"
): FeedEventResponse {
  return event(sequence, { source_type: "platform", kind, status });
}

function shape(items: FeedItem[]): string[] {
  return items.map((item) =>
    item.type === "event"
      ? item.event.event_id
      : `[${item.run.events.map((e) => e.event_id).join(",")}]`
  );
}

function runOf(items: FeedItem[], index: number): PlatformRun {
  const item = items[index];
  if (item.type !== "run") throw new Error(`item ${index} is not a run`);
  return item.run;
}

describe("folding platform events", () => {
  it("folds each run of two or more consecutive platform events into one", () => {
    const events = [
      platform(9),
      platform(8),
      event(7),
      platform(6),
      event(5),
      platform(4),
      platform(3),
      platform(2),
    ];
    expect(shape(feedItems(events, true))).toEqual([
      "[e9,e8]",
      "e7",
      "e6",
      "e5",
      "[e4,e3,e2]",
    ]);
  });

  it("leaves every event a row when folding is off", () => {
    const events = [platform(3), platform(2), event(1)];
    expect(shape(feedItems(events, false))).toEqual(["e3", "e2", "e1"]);
  });

  it("keys a run by its oldest event, the time range newest and oldest", () => {
    const run = runOf(
      feedItems([platform(9), platform(8), platform(7)], true),
      0
    );
    expect(run.id).toBe("run-e7");
    expect(run.newest).toBe("2026-10-19T10:09:00Z");
    expect(run.oldest).toBe("2026-10-19T10:07:00Z");
  });

  it("keeps a run's key as a new platform event joins it on top", () => {
    const before = feedItems([platform(2), platform(1), event(0)], true);
    const after = feedItems(
      applyRecorded([platform(2), platform(1), event(0)], platform(3)),
      true
    );
    expect(shape(after)).toEqual(["[e3,e2,e1]", "e0"]);
    expect(runOf(after, 0).id).toBe(runOf(before, 0).id);
  });

  it("lets a new platform event on top of another row start its own", () => {
    const base = [event(2), platform(1), platform(0)];
    const one = applyRecorded(base, platform(3));
    expect(shape(feedItems(one, true))).toEqual(["e3", "e2", "[e1,e0]"]);
    const two = applyRecorded(one, platform(4));
    expect(shape(feedItems(two, true))).toEqual(["[e4,e3]", "e2", "[e1,e0]"]);
  });
});

describe("a run's summary", () => {
  it("counts the kinds, the commonest first, ties by name", () => {
    expect(
      kindBreakdown([
        platform(1, "task.failed"),
        platform(2, "task.completed"),
        platform(3, "task.completed"),
        platform(4, "approval.requested"),
        platform(5, "task.failed"),
        platform(6, "task.completed"),
      ])
    ).toEqual([
      { kind: "task.completed", count: 3 },
      { kind: "task.failed", count: 2 },
      { kind: "approval.requested", count: 1 },
    ]);
  });

  it.each<[ProcessingStatus[], ProcessingStatus]>([
    [["handled", "error", "processing"], "error"],
    [["handled", "processing", "skipped"], "processing"],
    [["queued", "handled"], "queued"],
    [["skipped", "handled", "no_handlers"], "handled"],
    [["no_handlers", "skipped"], "skipped"],
    [["no_handlers", "no_handlers"], "no_handlers"],
  ])("shows the worst of %j as %s", (statuses, worst) => {
    const events = statuses.map((status, i) =>
      platform(i, "task.completed", status)
    );
    expect(worstStatus(events)).toBe(worst);
  });

  it("counts the events that have the worst status", () => {
    const run = runOf(
      feedItems(
        [
          platform(3, "task.failed", "error"),
          platform(2, "task.completed", "handled"),
          platform(1, "task.failed", "error"),
        ],
        true
      ),
      0
    );
    expect(run.worst).toBe("error");
    expect(run.worstCount).toBe(2);
  });

  it("has no worst status for no events", () => {
    expect(worstStatus([])).toBeUndefined();
  });
});

describe("when the feed folds", () => {
  it("folds an unfiltered feed and one narrowed to another stream or provider", () => {
    expect(groupsPlatformRuns({}, ["p1"])).toBe(true);
    expect(groupsPlatformRuns({ stream: "s1" }, ["p1"])).toBe(true);
    expect(groupsPlatformRuns({ source_type: "generic_webhook" }, ["p1"])).toBe(
      true
    );
  });

  it("does not fold once narrowed to the platform stream or provider", () => {
    expect(groupsPlatformRuns({ stream: "p1" }, ["p1"])).toBe(false);
    expect(groupsPlatformRuns({ source_type: "platform" }, ["p1"])).toBe(false);
  });
});

describe("moving through runs", () => {
  const items = feedItems(
    [event(9), platform(8), platform(7), platform(6), event(5)],
    true
  );
  const run = runOf(items, 1);

  it("opens a run the viewer opened, or one holding the selected event", () => {
    expect(isRunExpanded(run, new Set(), undefined)).toBe(false);
    expect(isRunExpanded(run, new Set([run.id]), undefined)).toBe(true);
    expect(isRunExpanded(run, new Set(), "e7")).toBe(true);
    expect(isRunExpanded(run, new Set(), "e9")).toBe(false);
  });

  it("finds the run an event is folded into", () => {
    expect(runHolding(items, "e7")?.id).toBe(run.id);
    expect(runHolding(items, "e9")).toBeUndefined();
    expect(runHolding(items, null)).toBeUndefined();
  });

  it("stops on a closed run once, and on its events once open", () => {
    const closed = feedStops(items, () => false);
    expect(closed).toEqual([
      { type: "event", id: "e9" },
      { type: "run", id: "run-e6" },
      { type: "event", id: "e5" },
    ]);
    const open = feedStops(items, () => true);
    expect(open.map((s) => s.id)).toEqual([
      "e9",
      "run-e6",
      "e8",
      "e7",
      "e6",
      "e5",
    ]);
  });

  it("steps from a row to the next, and starts at the top", () => {
    const stops = feedStops(items, () => false);
    expect(neighbourStop(stops, { type: "event", id: "e9" }, 1)).toEqual({
      type: "run",
      id: "run-e6",
    });
    expect(neighbourStop(stops, { type: "run", id: "run-e6" }, 1)).toEqual({
      type: "event",
      id: "e5",
    });
    expect(
      neighbourStop(stops, { type: "event", id: "e5" }, 1)
    ).toBeUndefined();
    expect(neighbourStop(stops, undefined, 1)).toEqual({
      type: "event",
      id: "e9",
    });
    expect(neighbourStop(stops, { type: "event", id: "gone" }, -1)).toEqual({
      type: "event",
      id: "e9",
    });
  });
});
