import { describe, expect, it } from "vitest";
import en from "../../messages/en.json";
import ru from "../../messages/ru.json";
import {
  getStreamOutcomeStatusPresentation,
  getTaskStatusPresentation,
  getTriggerStatusPresentation,
} from "./status";

describe("tasks waiting on a person", () => {
  it("read as one 'Needs action' status whatever they wait for", () => {
    const presentations = [
      "waiting_for_input",
      "waiting_for_approval",
      "waiting_for_continuation",
      "blocked",
      "input_required",
    ].map(getTaskStatusPresentation);

    for (const presentation of presentations) {
      expect(presentation).toEqual({
        label: "Needs action",
        labelKey: "needsAction",
        kind: "attention",
      });
    }
  });
});

describe("a stream subscriber's verdict", () => {
  it("asks for a look when the verdict is one this build does not know", () => {
    expect(getStreamOutcomeStatusPresentation("pending")).toEqual({
      label: "Unknown outcome",
      labelKey: "unknown",
      kind: "attention",
    });
  });
});

// A labelKey that is not a message key renders the raw key on screen; this
// happened to `needs_owner` on the trigger page.
describe("status labels are translated", () => {
  const cases: Array<{
    section: string;
    keys: string[];
    messages: (m: typeof en) => Record<string, string>;
  }> = [
    {
      section: "TriggersPage.status",
      keys: ["active", "inactive", "paused", "error", "needs_owner"].map(
        (s) => getTriggerStatusPresentation(s).labelKey ?? ""
      ),
      messages: (m) => m.TriggersPage.status,
    },
    {
      section: "EventsPage.filter",
      keys: ["reacted", "skipped", "error", "unheard", "pending"].map(
        (s) => getStreamOutcomeStatusPresentation(s).labelKey ?? ""
      ),
      messages: (m) => m.EventsPage.filter,
    },
  ];

  it.each(cases)("$section has every labelKey in both locales", (c) => {
    for (const locale of [en, ru]) {
      for (const key of c.keys) {
        expect(c.messages(locale as typeof en)).toHaveProperty(key);
      }
    }
  });
});
