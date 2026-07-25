import { describe, it, expect } from "vitest";
import { reduceState, applyEvent, initialState } from "./reducer";
import { EventInput } from "./contract";
import { A2UISurfaceState } from "./a2ui";

function surfaceOf(
  state: ReturnType<typeof reduceState>,
  surfaceId: string
): A2UISurfaceState | undefined {
  const part = state.parts.find((p) => p.partId === surfaceId);
  return part?.data.surface as A2UISurfaceState | undefined;
}

describe("reducer A2UI surface (supersede-by-surface_id)", () => {
  it("creates a surface part keyed by surface_id", () => {
    const state = reduceState([
      {
        eventType: "a2ui.create",
        data: { surface_id: "s1", catalog_id: "cat" },
      },
    ]);
    expect(state.parts).toHaveLength(1);
    expect(state.parts[0].kind).toBe("a2ui");
    expect(state.parts[0].partId).toBe("s1");
    const surface = surfaceOf(state, "s1");
    expect(surface?.catalog_id).toBe("cat");
    expect(surface?.components).toEqual({});
  });

  it("upserts components onto the surface without adding new parts", () => {
    const state = reduceState([
      { eventType: "a2ui.create", data: { surface_id: "s1" } },
      {
        eventType: "a2ui.update.components",
        data: {
          surface_id: "s1",
          components: [
            { id: "root", component: "Column", children: ["title"] },
            { id: "title", component: "Text", text: "Hello" },
          ],
        },
      },
    ]);
    expect(state.parts).toHaveLength(1);
    const surface = surfaceOf(state, "s1");
    expect(Object.keys(surface?.components ?? {})).toHaveLength(2);
    expect(surface?.components.root.component).toBe("Column");
  });

  it("overwrites an existing component on a later upsert", () => {
    const state = reduceState([
      { eventType: "a2ui.create", data: { surface_id: "s1" } },
      {
        eventType: "a2ui.update.components",
        data: {
          surface_id: "s1",
          components: [{ id: "title", component: "Text", text: "Old" }],
        },
      },
      {
        eventType: "a2ui.update.components",
        data: {
          surface_id: "s1",
          components: [{ id: "title", component: "Text", text: "New" }],
        },
      },
    ]);
    const surface = surfaceOf(state, "s1");
    expect(surface?.components.title.text).toBe("New");
  });

  it("patches the data model at a JSON Pointer path", () => {
    const state = reduceState([
      { eventType: "a2ui.create", data: { surface_id: "s1" } },
      {
        eventType: "a2ui.update.data",
        data: { surface_id: "s1", path: "/user/name", value: "Jane" },
      },
    ]);
    const surface = surfaceOf(state, "s1");
    expect((surface?.dataModel.user as { name?: string })?.name).toBe("Jane");
  });

  it("root path merges the whole data model", () => {
    const state = reduceState([
      { eventType: "a2ui.create", data: { surface_id: "s1" } },
      {
        eventType: "a2ui.update.data",
        data: { surface_id: "s1", path: "/", value: { foo: "bar" } },
      },
    ]);
    const surface = surfaceOf(state, "s1");
    expect(surface?.dataModel.foo).toBe("bar");
  });

  it("keeps two surfaces independent", () => {
    const state = reduceState([
      { eventType: "a2ui.create", data: { surface_id: "s1" } },
      { eventType: "a2ui.create", data: { surface_id: "s2" } },
      {
        eventType: "a2ui.update.components",
        data: {
          surface_id: "s1",
          components: [{ id: "root", component: "Card" }],
        },
      },
    ]);
    expect(state.parts).toHaveLength(2);
    expect(Object.keys(surfaceOf(state, "s1")?.components ?? {})).toHaveLength(
      1
    );
    expect(Object.keys(surfaceOf(state, "s2")?.components ?? {})).toHaveLength(
      0
    );
  });

  it("delete tombstones the surface part (removal path)", () => {
    const state = reduceState([
      { eventType: "tool.call", data: { tool_call_id: "tc" } },
      { eventType: "a2ui.create", data: { surface_id: "s1" } },
      { eventType: "a2ui.delete", data: { surface_id: "s1" } },
    ]);
    expect(state.parts.map((p) => p.partId)).toEqual(["tc"]);
    expect(surfaceOf(state, "s1")).toBeUndefined();
  });

  it("deleting one surface leaves the other", () => {
    const state = reduceState([
      { eventType: "a2ui.create", data: { surface_id: "s1" } },
      { eventType: "a2ui.create", data: { surface_id: "s2" } },
      { eventType: "a2ui.delete", data: { surface_id: "s1" } },
    ]);
    expect(state.parts.map((p) => p.partId)).toEqual(["s2"]);
  });

  it("normalizes workflow.-prefixed A2UI event names", () => {
    const events: EventInput[] = [
      { eventType: "workflow.a2ui.create", data: { surface_id: "s1" } },
      {
        eventType: "workflow.a2ui.update.components",
        data: {
          surface_id: "s1",
          components: [{ id: "root", component: "Card" }],
        },
      },
    ];
    const state = reduceState(events);
    expect(state.parts).toHaveLength(1);
    expect(state.parts[0].kind).toBe("a2ui");
    expect(surfaceOf(state, "s1")?.components.root).toBeDefined();
  });

  it("update before create seeds a surface then applies the update", () => {
    let state = initialState();
    state = applyEvent(state, {
      eventType: "a2ui.update.components",
      data: {
        surface_id: "s1",
        components: [{ id: "root", component: "Card" }],
      },
    });
    expect(state.parts).toHaveLength(1);
    expect(surfaceOf(state, "s1")?.components.root).toBeDefined();
  });
});
