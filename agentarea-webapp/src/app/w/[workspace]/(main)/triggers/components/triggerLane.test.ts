import { describe, expect, it } from "vitest";
import { getTriggerHealth, getTriggerLane } from "./triggerDisplay";

describe("which lane an automation belongs to", () => {
  it("keeps a schedule on the clock", () => {
    expect(getTriggerLane({ trigger_type: "cron" })).toBe("schedule");
  });

  it("reads a stream trigger that continues sessions as a channel", () => {
    expect(
      getTriggerLane({ trigger_type: "stream", session: { continue: true } })
    ).toBe("channel");
  });

  it("reads a stream trigger whose every event is its own task as an event", () => {
    expect(
      getTriggerLane({ trigger_type: "stream", session: { continue: false } })
    ).toBe("event");
    expect(getTriggerLane({ trigger_type: "stream", session: null })).toBe(
      "event"
    );
  });
});

describe("a trigger whose configurer left", () => {
  it("reads as needing a new owner, not merely paused", () => {
    expect(getTriggerHealth({ is_active: false, status: "needs_owner" })).toBe(
      "needs_owner"
    );
  });

  it("sits in the event lane when it listens to a stream", () => {
    expect(getTriggerLane({ trigger_type: "stream" })).toBe("event");
  });
});
