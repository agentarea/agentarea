import { describe, expect, it } from "vitest";
import type { FeedEventResponse, Processing } from "@/api/client/types.gen";
import {
  applyProcessing,
  applyRecorded,
  dayGroups,
  eventByIdHref,
  eventFate,
  feedApiQuery,
  feedHref,
  foldRuns,
  formatEventTime,
  legacyStreamQuery,
  liveQuery,
  matchesResult,
  neighbourEvent,
  parseFeedState,
  platformForced,
  platformOutcome,
  processingProgress,
  rowStatusQuiet,
  shortAge,
  showsPlatform,
  utcTitle,
} from "./eventFeed";

function processing(over: Partial<Processing> = {}): Processing {
  return {
    status: "queued",
    subscribers: null,
    reacted: 0,
    skipped: 0,
    errors: 0,
    tasks: [],
    ...over,
  };
}

function event(
  sequence: number,
  over: Partial<FeedEventResponse> = {}
): FeedEventResponse {
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
    summary: null,
    received_at: "2026-10-19T10:00:00Z",
    occurred_at: "2026-10-19T10:00:00Z",
    depth: 0,
    correlation_id: null,
    causation_id: null,
    attachments: 0,
    processing: processing(),
    ...over,
  };
}

describe("the feed's URL state", () => {
  it("reads the filters it knows and drops the rest", () => {
    expect(
      parseFeedState({
        stream: "s1",
        kind: "order.*",
        result: "error",
        session: "src:alice",
        event: "e1",
        tab: "grid",
        source_type: ["a", "b"],
      })
    ).toEqual({
      stream: "s1",
      kind: "order.*",
      result: "error",
      session: "src:alice",
      event: "e1",
    });
  });

  it("ignores a result the API does not have", () => {
    expect(parseFeedState({ result: "maybe" })).toEqual({});
  });

  it("reads the platform switch only as 1", () => {
    expect(parseFeedState({ platform: "0" })).toEqual({ platform: "0" });
    expect(parseFeedState({ platform: "1" })).toEqual({});
    expect(parseFeedState({ platform: "true" })).toEqual({});
    expect(feedHref({ platform: "0" }, { stream: "s1" })).toBe(
      "/events/s1?platform=0"
    );
  });

  it("writes a link, a patch replacing or removing values", () => {
    const state = { kind: "order.*", result: "error" as const, event: "e1" };
    expect(feedHref(state)).toBe("/events?kind=order.*&result=error&event=e1");
    expect(feedHref(state, { result: undefined, event: undefined })).toBe(
      "/events?kind=order.*"
    );
    expect(feedHref({})).toBe("/events");
  });

  it("puts the stream in the path and keeps the other filters in the query", () => {
    const state = { stream: "s 1", result: "error" as const, event: "e1" };
    expect(feedHref(state)).toBe("/events/s%201?result=error&event=e1");
    expect(feedHref({ stream: "s1" })).toBe("/events/s1");
    expect(feedHref(state, { stream: undefined, event: undefined })).toBe(
      "/events?result=error"
    );
  });

  it("links an event by its id", () => {
    expect(eventByIdHref("a/b")).toBe("/events/event/a%2Fb");
  });

  it("names the API's parameters, and live leaves the result out", () => {
    const state = {
      stream: "s1",
      source_type: "mail",
      kind: "order.*",
      result: "handled" as const,
      session: "x",
      sender: "bob",
      event: "e1",
    };
    expect(feedApiQuery(state, true)).toEqual({
      stream_id: "s1",
      source_type: "mail",
      kind: "order.*",
      result: "handled",
      session_key: "x",
      sender: "bob",
      platform: undefined,
    });
    expect(liveQuery(state, true)).toBe(
      "stream_id=s1&source_type=mail&kind=order.*&session_key=x&sender=bob"
    );
  });

  it("asks without the platform's events unless they are shown, live too", () => {
    expect(feedApiQuery({}, false)).toMatchObject({ platform: false });
    expect(liveQuery({ kind: "order.*" }, false)).toBe(
      "kind=order.*&platform=false"
    );
  });
});

describe("the platform's own events", () => {
  const platformStreams = ["p1"];

  it("are shown unless the switch is off", () => {
    expect(showsPlatform({}, platformStreams)).toBe(true);
    expect(showsPlatform({ stream: "s1" }, platformStreams)).toBe(true);
    expect(showsPlatform({ platform: "0" }, platformStreams)).toBe(false);
  });

  it("are shown whatever the switch says when the view is the platform's", () => {
    for (const state of [
      { stream: "p1", platform: "0" as const },
      { source_type: "platform", platform: "0" as const },
    ]) {
      expect(platformForced(state, platformStreams)).toBe(true);
      expect(showsPlatform(state, platformStreams)).toBe(true);
    }
    expect(platformForced({ platform: "0" }, platformStreams)).toBe(false);
  });
});

describe("what the platform did, as a row shows it", () => {
  it("counts reactions against subscribers", () => {
    expect(
      processingProgress(
        processing({ status: "processing", subscribers: 3, reacted: 1 })
      )
    ).toEqual({ done: 1, total: 3, tasks: 0, skipped: 0, errors: 0 });
  });

  it("a subscription that reacted without being counted still ends it", () => {
    expect(
      processingProgress(
        processing({ status: "handled", subscribers: 1, reacted: 2 })
      ).total
    ).toBe(2);
  });

  it("has no total until routed", () => {
    expect(processingProgress(processing()).total).toBe(0);
  });
});

describe("live updates", () => {
  it("puts a new event on top once, newest sequence first", () => {
    const rows = [event(5), event(3)];
    const added = applyRecorded(rows, event(4));
    expect(added.map((e) => e.sequence)).toEqual([5, 4, 3]);
    expect(applyRecorded(added, event(4))).toBe(added);
  });

  it("a repeat of a known event takes its newer processing", () => {
    const rows = [event(5)];
    const again = event(5, {
      processing: processing({ status: "handled", subscribers: 1, reacted: 1 }),
    });
    expect(applyRecorded(rows, again)[0].processing.status).toBe("handled");
  });

  it("moves an event's status, and leaves an unknown one alone", () => {
    const rows = [event(5), event(3)];
    const moved = applyProcessing(
      rows,
      "e3",
      processing({ status: "error", subscribers: 2, reacted: 2, errors: 1 })
    );
    expect(moved[1].processing.status).toBe("error");
    expect(moved[0]).toBe(rows[0]);
    expect(applyProcessing(rows, "e9", processing())).toBe(rows);
  });

  it("filters by result where the server did not", () => {
    const handled = event(1, {
      processing: processing({ status: "handled" }),
    });
    expect(matchesResult(handled, undefined)).toBe(true);
    expect(matchesResult(handled, "handled")).toBe(true);
    expect(matchesResult(handled, "error")).toBe(false);
  });
});

describe("grouping and moving through the list", () => {
  it("groups by the viewer's day, newest first", () => {
    const now = new Date("2026-10-19T12:00:00Z");
    const groups = dayGroups(
      [
        event(3, { received_at: "2026-10-19T09:00:00Z" }),
        event(2, { received_at: "2026-10-18T23:30:00Z" }),
        event(1, { received_at: "2026-10-15T08:00:00Z" }),
      ],
      now,
      "UTC"
    );
    expect(groups.map((g) => [g.day, g.relative, g.events.length])).toEqual([
      ["2026-10-19", "today", 1],
      ["2026-10-18", "yesterday", 1],
      ["2026-10-15", null, 1],
    ]);
  });

  it("uses the time zone it is given", () => {
    const now = new Date("2026-10-19T12:00:00Z");
    const [group] = dayGroups(
      [event(1, { received_at: "2026-10-18T23:30:00Z" })],
      now,
      "Europe/Moscow"
    );
    expect(group.relative).toBe("today");
  });

  it("steps to the next or previous event and stops at the ends", () => {
    const rows = [event(3), event(2), event(1)];
    expect(neighbourEvent(rows, "e2", 1)).toBe("e1");
    expect(neighbourEvent(rows, "e2", -1)).toBe("e3");
    expect(neighbourEvent(rows, "e1", 1)).toBeUndefined();
    expect(neighbourEvent(rows, undefined, 1)).toBe("e3");
  });
});

describe("how long an event has waited", () => {
  it("reads in the largest whole unit", () => {
    expect(shortAge(-500)).toBe("0s");
    expect(shortAge(3_400)).toBe("3s");
    expect(shortAge(125_000)).toBe("2m");
    expect(shortAge(3 * 3_600_000 + 5)).toBe("3h");
    expect(shortAge(50 * 3_600_000)).toBe("2d");
  });
});

describe("a stream page URL from before the shared feed", () => {
  it("reads its outcome as a result and its event as a sequence", () => {
    expect(legacyStreamQuery({ outcome: "unheard", event: "12" })).toEqual({
      result: "no_handlers",
      sequence: 12,
    });
    expect(legacyStreamQuery({ outcome: "reacted" })).toEqual({
      result: "handled",
    });
  });

  it("drops an outcome of all, and one it does not know", () => {
    expect(legacyStreamQuery({ outcome: "all" })).toEqual({});
    expect(legacyStreamQuery({ outcome: "unknown" })).toEqual({});
  });

  it("is null for a URL of the shared feed", () => {
    expect(legacyStreamQuery({})).toBeNull();
    expect(legacyStreamQuery({ event: "8f2c-uuid", result: "error" })).toBe(
      null
    );
  });
});

describe("which rows show their result as a glyph alone", () => {
  it("is the results that need no reading", () => {
    expect(
      [
        "no_handlers",
        "skipped",
        "handled",
        "queued",
        "processing",
        "error",
      ].filter((s) => rowStatusQuiet(s as Processing["status"]))
    ).toEqual(["no_handlers", "skipped", "handled"]);
  });
});

describe("an event's time", () => {
  const iso = "2026-10-19T10:00:00Z";

  it("is shown in the viewer's zone", () => {
    expect(formatEventTime(iso, "en-GB", "Europe/Berlin", "time")).toBe(
      "12:00"
    );
    expect(formatEventTime("2026-10-19T10:00:00", "en-GB", "UTC", "time")).toBe(
      "10:00"
    );
    expect(formatEventTime("not a time", "en-GB", "UTC", "time")).toBe("—");
  });

  it("titles the zone's full time with UTC beside it, once when they are one", () => {
    expect(utcTitle(iso, "en-GB", "Europe/Berlin")).toBe(
      `${formatEventTime(iso, "en-GB", "Europe/Berlin", "full")} · ${formatEventTime(iso, "en-GB", "UTC", "full")}`
    );
    expect(utcTitle(iso, "en-GB", "Europe/Berlin")).toContain("12:00:00");
    expect(utcTitle(iso, "en-GB", "Europe/Berlin")).toContain("10:00:00 UTC");
    expect(utcTitle(iso, "en-GB", "UTC")).toBe(
      formatEventTime(iso, "en-GB", "UTC", "full")
    );
  });
});

describe("what became of an event, in a row's words", () => {
  it("says nobody listens, the handlers passed, or they failed", () => {
    expect(eventFate(processing({ status: "no_handlers" }))).toEqual({
      key: "nobody",
    });
    expect(eventFate(processing({ status: "skipped" }))).toEqual({
      key: "skipped",
    });
    expect(eventFate(processing({ status: "error", errors: 2 }))).toEqual({
      key: "failed",
      count: 2,
    });
  });

  it("names the tasks it started by the one that most needs a look", () => {
    const tasks = (...statuses: string[]) =>
      processing({
        status: "handled",
        reacted: statuses.length,
        tasks: statuses.map((status, i) => ({ id: `t${i}`, status })),
      });
    expect(eventFate(tasks("completed"))).toEqual({
      key: "tasks",
      count: 1,
      status: "done",
    });
    expect(eventFate(tasks("completed", "running"))).toMatchObject({
      status: "running",
    });
    expect(eventFate(tasks("running", "waiting_for_approval"))).toMatchObject({
      status: "attention",
    });
    expect(eventFate(tasks("waiting_for_input", "failed"))).toMatchObject({
      count: 2,
      status: "failed",
    });
  });

  it("is passed on when the handlers reacted without a task", () => {
    expect(
      eventFate(processing({ status: "handled", reacted: 2, tasks: [] }))
    ).toEqual({ key: "passedOn" });
  });
});

describe("what a platform event says about a task", () => {
  it("is the task's outcome with its status", () => {
    expect(platformOutcome("task.completed")).toEqual({
      key: "completed",
      status: "done",
    });
    expect(platformOutcome("task.failed")?.status).toBe("failed");
    expect(platformOutcome("task.cancelled")?.status).toBe("cancelled");
    expect(platformOutcome("approval.requested")).toEqual({
      key: "approval",
      status: "attention",
    });
    expect(platformOutcome("input.request")?.key).toBe("input");
  });

  it("is nothing for a kind the platform does not write", () => {
    expect(platformOutcome("webhook")).toBeNull();
  });
});

describe("a run of alike events, as the feed folds it", () => {
  const ids = (items: ReturnType<typeof foldRuns>) =>
    items.map((i) => [i.event.event_id, i.folded.map((e) => e.event_id)]);

  it("folds neighbours from one stream that say and came to the same", () => {
    const events = [
      event(4),
      event(3),
      event(2, { kind: "order.refunded" }),
      event(1),
    ];
    expect(ids(foldRuns(events, new Set()))).toEqual([
      ["e4", ["e3"]],
      ["e2", []],
      ["e1", []],
    ]);
  });

  it("keeps apart what differs in stream, summary, sender or fate", () => {
    const events = [
      event(5),
      event(4, { stream_id: "s2" }),
      event(3, { summary: "Disk full" }),
      event(2, { sender: "ann" }),
      event(1, { processing: processing({ status: "no_handlers" }) }),
    ];
    expect(
      foldRuns(events, new Set()).every((i) => i.folded.length === 0)
    ).toBe(true);
  });

  it("unfolds the run an open event is in", () => {
    const events = [event(3), event(2), event(1)];
    expect(foldRuns(events, new Set(["e2"])).length).toBe(3);
  });

  it("leaves a run unfolded once it is opened", () => {
    const events = [event(3), event(2), event(1)];
    expect(ids(foldRuns(events, new Set(["e3"])))).toEqual([
      ["e3", []],
      ["e2", []],
      ["e1", []],
    ]);
  });
});
