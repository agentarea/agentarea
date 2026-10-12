import { describe, expect, it } from "vitest";
import { insideContour, perimeterContour, skeleton } from "./perimeterContour";

const square = (x: number, y: number, half = 20) => ({
  x1: x - half,
  y1: y - half,
  x2: x + half,
  y2: y + half,
});

describe("skeleton", () => {
  it("spans every member, preferring the links that exist", () => {
    const centres = [
      { x: 0, y: 0 },
      { x: 100, y: 0 },
      { x: 50, y: 10 },
    ];
    const bones = skeleton(centres, (a, b) => a + b === 1);
    expect(bones).toHaveLength(2);
    expect(bones).toContainEqual([centres[0], centres[1]]);
  });
});

describe("perimeterContour", () => {
  it("joins members along their bones into one shape", () => {
    const a = { x: 0, y: 0 };
    const b = { x: 300, y: 0 };
    const loops = perimeterContour(
      [square(0, 0), square(300, 0)],
      [[a, b]],
      []
    );
    expect(loops).toHaveLength(1);
    expect(insideContour({ x: 150, y: 0 }, loops)).toBe(true);
  });

  it("gives way around an outsider in the way", () => {
    const loops = perimeterContour(
      [square(0, 0), square(300, 0), square(150, 120)],
      [
        [
          { x: 0, y: 0 },
          { x: 150, y: 120 },
        ],
        [
          { x: 150, y: 120 },
          { x: 300, y: 0 },
        ],
      ],
      [square(150, 0)]
    );
    expect(insideContour({ x: 150, y: 0 }, loops)).toBe(false);
    expect(insideContour({ x: 150, y: 120 }, loops)).toBe(true);
  });

  it("draws nothing for no members", () => {
    expect(perimeterContour([], [], [square(0, 0)])).toEqual([]);
  });
});
