import { describe, expect, it } from "vitest";
import type { Part } from "@/lib/events/contract";
import {
  applyEvent,
  initialState,
  type CompletedRun,
} from "@/lib/events/reducer";
import {
  buildActivitySegments,
  hasVisibleAssistantContent,
  lastVisibleAssistantContent,
  shouldRenderConversationFallback,
} from "./activityView";

const llm = (id: string, content: string): Part => ({
  partId: id,
  kind: "llm",
  eventType: "llm.call.completed",
  data: { content },
});
const tool = (id: string, success = true): Part => ({
  partId: id,
  kind: "tool",
  eventType: "tool.result",
  data: { tool_name: "read_file", success },
});
const completed = (
  id: string,
  parts: Part[],
  terminalAnswer: string | null = null
): CompletedRun => ({
  id,
  partIds: parts.map((p) => p.partId),
  terminalType: "task.completed",
  terminalMessage: "Task completed.",
  terminalAnswer,
});
describe("activity view", () => {
  it("keeps the record fallback for a settled transcript with no answer", () => {
    expect(shouldRenderConversationFallback(false, [])).toBe(true);
    expect(shouldRenderConversationFallback(true, [])).toBe(false);
  });
  it("does not treat an LLM response as task completion", () => {
    const segments = buildActivitySegments(
      [tool("t"), llm("a", "Still working")],
      []
    );
    expect(segments).toHaveLength(1);
    expect(segments[0].kind === "work" && segments[0].run.completed).toBe(
      false
    );
  });
  it("keeps text-only answers visible without empty work boxes", () => {
    const parts = [llm("a", "Answer")];
    expect(
      buildActivitySegments(parts, [completed("run-1", parts)]).map(
        (s) => s.kind
      )
    ).toEqual(["answer"]);
  });
  it("preserves narration and extracts one final answer", () => {
    const parts = [llm("intro", "Checking"), tool("t"), llm("a", "Done")];
    const segments = buildActivitySegments(parts, [
      completed("run-1", parts, "Done"),
    ]);
    expect(segments.map((s) => s.kind)).toEqual(["work", "answer"]);
    expect(
      segments[0].kind === "work" && segments[0].run.parts.map((p) => p.partId)
    ).toEqual(["intro", "t"]);
  });
  it("uses explicit final response instead of promoting progress", () => {
    const parts = [llm("intro", "Checking"), tool("t")];
    const segments = buildActivitySegments(parts, [
      completed("run-1", parts, "Actual final"),
    ]);
    expect(
      segments
        .filter((s) => s.kind === "answer")
        .map((s) => s.kind !== "work" && s.part.data.content)
    ).toEqual(["Actual final"]);
    expect(segments[0].kind === "work" && segments[0].run.parts).toEqual(parts);
  });
  it("keeps a terminal answer when every snapshotted part was deleted", () => {
    let state = applyEvent(initialState(), {
      eventType: "a2ui.create",
      data: { surface_id: "surface" },
    });
    state = applyEvent(state, {
      eventType: "task.completed",
      data: { final_response: "Preserve this answer" },
    });
    state = applyEvent(state, {
      eventType: "a2ui.delete",
      data: { surface_id: "surface" },
    });

    expect(buildActivitySegments(state.parts, state.completedRuns)).toEqual([
      expect.objectContaining({
        kind: "answer",
        part: expect.objectContaining({
          data: { content: "Preserve this answer" },
        }),
      }),
    ]);
  });
  it("gives a terminal-only answer ownership over a result fallback", () => {
    const state = applyEvent(initialState(), {
      eventType: "task.completed",
      data: { final_response: "Один финальный ответ" },
    });
    const segments = buildActivitySegments(state.parts, state.completedRuns);

    expect(segments).toEqual([
      expect.objectContaining({
        kind: "answer",
        part: expect.objectContaining({
          data: { content: "Один финальный ответ" },
        }),
      }),
    ]);
    expect(hasVisibleAssistantContent(segments)).toBe(true);
    expect(lastVisibleAssistantContent(segments)).toBe("Один финальный ответ");
    expect(shouldRenderConversationFallback(false, segments)).toBe(false);
  });
  it("exposes a synthetic failed answer for terminal-message deduplication", () => {
    const state = applyEvent(initialState(), {
      eventType: "task.failed",
      data: { reason: "Одинаковая ошибка", result: "Одинаковая ошибка" },
    });
    const segments = buildActivitySegments(state.parts, state.completedRuns);

    expect(lastVisibleAssistantContent(segments)).toBe("Одинаковая ошибка");
    expect(state.terminalMessage).toBe("Одинаковая ошибка");
  });
  it("treats an active stream as visible assistant content", () => {
    const streaming: Part = {
      partId: "execution:0",
      kind: "llm",
      eventType: "llm.call.chunk",
      data: { chunk: "Печатаю ответ" },
    };
    const segments = buildActivitySegments([streaming], []);

    expect(hasVisibleAssistantContent(segments)).toBe(true);
    expect(shouldRenderConversationFallback(false, segments)).toBe(false);
  });
  it("replaces streaming prose with one completed answer", () => {
    const state = applyEvent(
      applyEvent(initialState(), {
        eventType: "llm.call.chunk",
        data: { execution_id: "execution", iteration: 0, chunk: "Черновик" },
      }),
      {
        eventType: "llm.call.completed",
        data: {
          execution_id: "execution",
          iteration: 0,
          content: "Финальный ответ",
        },
      }
    );
    const completedState = applyEvent(state, {
      eventType: "task.completed",
      data: { final_response: "Финальный ответ" },
    });
    const segments = buildActivitySegments(
      completedState.parts,
      completedState.completedRuns
    );

    expect(
      segments
        .filter((segment) => segment.kind === "answer")
        .map((segment) => segment.kind !== "work" && segment.part.data.content)
    ).toEqual(["Финальный ответ"]);
  });
  it("promotes the final full chunk when completion has no llm-completed event", () => {
    const chunk: Part = {
      partId: "execution:0",
      kind: "llm",
      eventType: "llm.call.chunk",
      data: { chunk: "Финальный ответ" },
    };
    const segments = buildActivitySegments(
      [chunk],
      [completed("run-1", [chunk], "Финальный ответ")]
    );

    expect(segments).toEqual([
      expect.objectContaining({
        kind: "answer",
        part: expect.objectContaining({
          partId: "execution:0",
          eventType: "llm.call.completed",
          data: expect.objectContaining({ content: "Финальный ответ" }),
        }),
      }),
    ]);
  });
  it("does not let a hidden A2UI payload suppress the record fallback", () => {
    const hidden: Part = {
      partId: "execution:0",
      kind: "llm",
      eventType: "llm.call.chunk",
      data: { chunk: '---a2ui_JSON---\n{"surface":"hidden"}' },
    };
    const segments = buildActivitySegments([hidden], []);

    expect(hasVisibleAssistantContent(segments)).toBe(false);
    expect(shouldRenderConversationFallback(false, segments)).toBe(true);
  });
  it("keeps group identity stable at completion", () => {
    const parts = [llm("intro", "Checking"), tool("t")];
    const before = buildActivitySegments(parts, []);
    const ended = [...parts, llm("a", "Done")];
    const after = buildActivitySegments(ended, [completed("run-1", ended)]);
    expect(before[0].kind === "work" && before[0].run.id).toBe(
      after[0].kind === "work" && after[0].run.id
    );
  });
  it("keeps human actions and artifacts outside collapsible work in order", () => {
    const form: Part = {
      partId: "f",
      kind: "form",
      eventType: "approval.request",
      data: {},
    };
    const artifact: Part = {
      partId: "file",
      kind: "artifact",
      eventType: "artifact.created",
      data: {},
    };
    const parts = [tool("t1"), form, tool("t2"), artifact, llm("a", "Done")];
    expect(
      buildActivitySegments(parts, [completed("run-1", parts)]).map(
        (s) => s.kind
      )
    ).toEqual(["work", "visible", "work", "visible", "answer"]);
  });
  it("uses late results and tolerates removed parts without hiding new work", () => {
    const segments = buildActivitySegments(
      [tool("t1", false), tool("t2")],
      [completed("run-1", [tool("t1"), tool("removed")])]
    );
    expect(segments[0].kind === "work" && segments[0].run.errorCount).toBe(1);
    expect(segments[1].kind === "work" && segments[1].run.completed).toBe(
      false
    );
  });
  it("keeps two completed runs and their answers separate", () => {
    const a = [tool("t1"), llm("a1", "First")],
      b = [tool("t2"), llm("a2", "Second")];
    expect(
      buildActivitySegments(
        [...a, ...b],
        [completed("run-1", a), completed("run-2", b)]
      ).map((s) => s.kind)
    ).toEqual(["work", "answer", "work", "answer"]);
  });
  it("preserves identical answers from separate runs", () => {
    const first = [llm("a1", "Same answer")];
    const second = [llm("a2", "Same answer")];
    const segments = buildActivitySegments(
      [...first, ...second],
      [
        completed("run-1", first, "Same answer"),
        completed("run-2", second, "Same answer"),
      ]
    );

    expect(
      segments
        .filter((segment) => segment.kind === "answer")
        .map((segment) => segment.kind !== "work" && segment.part.partId)
    ).toEqual(["a1", "a2"]);
  });
});
describe("terminal snapshots", () => {
  it("ignores repeated terminal events without new work", () => {
    let s = applyEvent(initialState(), {
      eventType: "tool.result",
      data: { tool_call_id: "t" },
    });
    s = applyEvent(s, { eventType: "task.completed", data: {} });
    s = applyEvent(s, { eventType: "task.completed", data: {} });
    expect(s.completedRuns).toHaveLength(1);
  });
  it("tracks new IDs after a completed surface was deleted", () => {
    let s = applyEvent(initialState(), {
      eventType: "a2ui.create",
      data: { surface_id: "surface" },
    });
    s = applyEvent(s, { eventType: "task.completed", data: {} });
    s = applyEvent(s, {
      eventType: "a2ui.delete",
      data: { surface_id: "surface" },
    });
    s = applyEvent(s, {
      eventType: "tool.result",
      data: { tool_call_id: "new" },
    });
    s = applyEvent(s, { eventType: "task.completed", data: {} });
    expect(s.completedRuns[1].partIds).toEqual(["new"]);
  });

  it("records a second terminal-only answer after a continuation boundary", () => {
    const state = applyEvent(
      applyEvent(
        applyEvent(
          applyEvent(initialState(), {
            eventType: "task.started",
            data: {},
          }),
          { eventType: "task.completed", data: { final_response: "First" } }
        ),
        { eventType: "task.continued", data: {} }
      ),
      { eventType: "task.completed", data: { final_response: "Second" } }
    );

    expect(state.completedRuns.map((run) => run.terminalAnswer)).toEqual([
      "First",
      "Second",
    ]);
  });

  it("dedupes a repeated terminal answer without a new run boundary", () => {
    const first = applyEvent(initialState(), {
      eventType: "task.completed",
      data: { final_response: "First" },
    });
    const repeated = applyEvent(first, {
      eventType: "task.completed",
      data: { final_response: "First" },
    });

    expect(repeated.completedRuns).toHaveLength(1);
  });
});
