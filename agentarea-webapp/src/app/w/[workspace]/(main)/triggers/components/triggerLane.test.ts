import { describe, expect, it } from "vitest";
import {
  findTriggerCatalogEntry,
  getTriggerHealth,
  getTriggerLane,
} from "./triggerDisplay";

describe("which lane an automation belongs to", () => {
  it("takes the catalog's word over anything inferred", () => {
    expect(
      getTriggerLane(
        { trigger_type: "webhook", data_extractor: null },
        { kind: "messaging" }
      )
    ).toBe("channel");
    expect(
      getTriggerLane(
        { trigger_type: "webhook", data_extractor: "telegram" },
        { kind: "event" }
      )
    ).toBe("event");
    expect(
      getTriggerLane({ trigger_type: "webhook" }, { kind: "schedule" })
    ).toBe("schedule");
  });

  it("reads a channel off its extractor when the catalog is absent", () => {
    expect(
      getTriggerLane({ trigger_type: "webhook", data_extractor: "telegram" })
    ).toBe("channel");
  });

  it("treats a bare webhook as somebody else's event", () => {
    expect(getTriggerLane({ trigger_type: "webhook" })).toBe("event");
    expect(
      getTriggerLane({ trigger_type: "webhook", webhook_type: "github" })
    ).toBe("event");
  });

  it("keeps a polling schedule on the clock, extractor and all", () => {
    expect(
      getTriggerLane({ trigger_type: "cron", data_extractor: "imap" })
    ).toBe("schedule");
    expect(getTriggerLane({ trigger_type: "cron" })).toBe("schedule");
  });

  it("ignores a catalog entry that claims no kind", () => {
    expect(getTriggerLane({ trigger_type: "cron" }, { name: "Schedule" })).toBe(
      "schedule"
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

describe("which catalog entry draws a trigger", () => {
  it("draws a stream trigger as the stream source, not the first entry without a webhook type", () => {
    const catalog = [
      { id: "cron", kind: "schedule" },
      { id: "webhook", kind: "event", webhook_type: "generic" },
      { id: "stream", kind: "event" },
    ];
    expect(
      findTriggerCatalogEntry({ trigger_type: "stream" }, catalog)?.id
    ).toBe("stream");
  });
});
