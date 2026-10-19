import { describe, expect, it } from "vitest";
import type { FeedEventResponse, Processing } from "@/api/client/types.gen";
import {
  applyProcessing,
  applyRecorded,
  dayGroups,
  feedApiQuery,
  feedHref,
  liveQuery,
  matchesResult,
  neighbourEvent,
  parseFeedState,
  processingProgress,
  shortAge,
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

  it("writes a link, a patch replacing or removing values", () => {
    const state = { stream: "s1", result: "error" as const, event: "e1" };
    expect(feedHref(state)).toBe("/events?stream=s1&result=error&event=e1");
    expect(feedHref(state, { result: undefined, event: undefined })).toBe(
      "/events?stream=s1"
    );
    expect(feedHref({})).toBe("/events");
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
    expect(feedApiQuery(state)).toEqual({
      stream_id: "s1",
      source_type: "mail",
      kind: "order.*",
      result: "handled",
      session_key: "x",
      sender: "bob",
    });
    expect(liveQuery(state)).toBe(
      "stream_id=s1&source_type=mail&kind=order.*&session_key=x&sender=bob"
    );
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
