import { describe, expect, it } from "vitest";
import { getTriggerLane } from "./triggerDisplay";

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
    expect(
      getTriggerLane({ trigger_type: "cron" }, { name: "Schedule" })
    ).toBe("schedule");
  });
});
