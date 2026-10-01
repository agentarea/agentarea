import { describe, expect, it } from "vitest";
import { hierarchyPositions, shelfPositions } from "./hierarchyLayout";

const nodes = [
  { id: "lead", size: 40 },
  { id: "a", size: 30 },
  { id: "b", size: 30 },
];
const edges = [
  { source: "lead", target: "a" },
  { source: "lead", target: "b" },
  { source: "lead", target: "missing" },
];

function at(positions: Map<string, { x: number; y: number }>, id: string) {
  const position = positions.get(id);
  if (!position) throw new Error(`no position for ${id}`);
  return position;
}

describe("hierarchyPositions", () => {
  it("places delegates below their lead top-down and to the right left-to-right", () => {
    const down = hierarchyPositions(nodes, edges, "TB");
    expect(at(down, "a").y).toBeGreaterThan(at(down, "lead").y);
    const across = hierarchyPositions(nodes, edges, "LR");
    expect(at(across, "b").x).toBeGreaterThan(at(across, "lead").x);
  });

  it("gives the same positions whatever order the input arrives in", () => {
    const first = hierarchyPositions(nodes, edges, "TB");
    const second = hierarchyPositions(
      [...nodes].reverse(),
      [...edges].reverse(),
      "TB"
    );
    expect([...second.entries()].sort()).toEqual([...first.entries()].sort());
    expect(first.has("missing")).toBe(false);
  });
});

describe("shelfPositions", () => {
  it("fills rows left to right within the given width", () => {
    const positions = shelfPositions(["a", "b", "c"], { x: 0, y: 0 }, 300);
    expect(positions.get("a")).toEqual({ x: 75, y: 50 });
    expect(positions.get("b")).toEqual({ x: 225, y: 50 });
    expect(positions.get("c")).toEqual({ x: 75, y: 150 });
  });

  it("keeps at least one column when the width is narrower than a cell", () => {
    const positions = shelfPositions(["a", "b"], { x: 10, y: 20 }, 40);
    expect(positions.get("b")).toEqual({ x: 85, y: 170 });
  });
});
