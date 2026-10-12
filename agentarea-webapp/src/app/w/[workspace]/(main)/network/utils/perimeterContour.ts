export interface Point {
  x: number;
  y: number;
}

export interface Rect {
  x1: number;
  y1: number;
  x2: number;
  y2: number;
}

export type Segment = [Point, Point];

// Reach of a member's pull, and of the skeleton's: the outline settles where
// the field drops to THRESHOLD, about a third of the way out.
const NODE_REACH = 84;
const SKELETON_REACH = 76;
const OUTSIDER_REACH = 46;
const OUTSIDER_PUSH = 3;
const THRESHOLD = 0.3;

function rectDistance(point: Point, rect: Rect) {
  const dx = Math.max(rect.x1 - point.x, 0, point.x - rect.x2);
  const dy = Math.max(rect.y1 - point.y, 0, point.y - rect.y2);
  return Math.hypot(dx, dy);
}

function segmentDistance(point: Point, [a, b]: Segment) {
  const dx = b.x - a.x;
  const dy = b.y - a.y;
  const length = dx * dx + dy * dy;
  const t =
    length === 0
      ? 0
      : Math.max(
          0,
          Math.min(1, ((point.x - a.x) * dx + (point.y - a.y) * dy) / length)
        );
  return Math.hypot(point.x - (a.x + t * dx), point.y - (a.y + t * dy));
}

function falloff(distance: number, reach: number) {
  return distance < reach ? (1 - distance / reach) ** 2 : 0;
}

/**
 * The spanning tree that holds the members together: the cheapest set of
 * links that reaches every one of them, preferring links that exist in the
 * graph (`linked`) over bare proximity. The outline follows it, so members
 * that work together sit in one shape instead of a hull swallowing whatever
 * lies between them.
 */
export function skeleton(
  centres: Point[],
  linked: (a: number, b: number) => boolean
): Segment[] {
  if (centres.length < 2) return [];
  const cost = (a: number, b: number) =>
    Math.hypot(centres[a].x - centres[b].x, centres[a].y - centres[b].y) *
    (linked(a, b) ? 0.25 : 1);
  const joined = new Set([0]);
  const best = centres.map((_, index) => ({ cost: cost(0, index), from: 0 }));
  const segments: Segment[] = [];
  while (joined.size < centres.length) {
    let next = -1;
    for (let index = 0; index < centres.length; index += 1) {
      if (joined.has(index)) continue;
      if (next === -1 || best[index].cost < best[next].cost) next = index;
    }
    joined.add(next);
    segments.push([centres[best[next].from], centres[next]]);
    for (let index = 0; index < centres.length; index += 1) {
      if (joined.has(index)) continue;
      const through = cost(next, index);
      if (through < best[index].cost)
        best[index] = { cost: through, from: next };
    }
  }
  return segments;
}

/**
 * An outline around `members` that follows `bones` between them and gives way
 * around `outsiders` — a bubble set. Members and bones pull the field up,
 * outsiders push it down, and the outline is where it crosses the threshold,
 * traced by marching squares. Returns closed loops; an outsider caught in the
 * middle comes out as a hole, read with the even-odd rule.
 */
export function perimeterContour(
  members: Rect[],
  bones: Segment[],
  outsiders: Rect[],
  cell = 8
): Point[][] {
  if (!members.length) return [];
  const pad = NODE_REACH + cell * 2;
  const x0 = Math.min(...members.map((rect) => rect.x1)) - pad;
  const y0 = Math.min(...members.map((rect) => rect.y1)) - pad;
  const x1 = Math.max(...members.map((rect) => rect.x2)) + pad;
  const y1 = Math.max(...members.map((rect) => rect.y2)) + pad;
  const columns = Math.ceil((x1 - x0) / cell) + 1;
  const rows = Math.ceil((y1 - y0) / cell) + 1;

  const field = new Float64Array(columns * rows);
  for (let row = 0; row < rows; row += 1) {
    for (let column = 0; column < columns; column += 1) {
      const point = { x: x0 + column * cell, y: y0 + row * cell };
      let value = 0;
      for (const rect of members)
        value += falloff(rectDistance(point, rect), NODE_REACH);
      for (const bone of bones)
        value += falloff(segmentDistance(point, bone), SKELETON_REACH);
      for (const rect of outsiders)
        value -=
          OUTSIDER_PUSH * falloff(rectDistance(point, rect), OUTSIDER_REACH);
      field[row * columns + column] = value;
    }
  }
  const at = (column: number, row: number) => field[row * columns + column];

  // Each crossing is named by the grid edge it lies on, so the segments of
  // neighbouring cells meet at the same key and can be chained into loops.
  const crossings = new Map<string, Point>();
  const crossingOn = (
    ca: number,
    ra: number,
    cb: number,
    rb: number
  ): string => {
    const key = `${ca},${ra},${cb},${rb}`;
    if (!crossings.has(key)) {
      const va = at(ca, ra);
      const vb = at(cb, rb);
      const t = (THRESHOLD - va) / (vb - va);
      crossings.set(key, {
        x: x0 + (ca + (cb - ca) * t) * cell,
        y: y0 + (ra + (rb - ra) * t) * cell,
      });
    }
    return key;
  };
  const links = new Map<string, string[]>();
  const link = (a: string, b: string) => {
    links.set(a, [...(links.get(a) ?? []), b]);
    links.set(b, [...(links.get(b) ?? []), a]);
  };

  for (let row = 0; row < rows - 1; row += 1) {
    for (let column = 0; column < columns - 1; column += 1) {
      const tl = at(column, row) >= THRESHOLD;
      const tr = at(column + 1, row) >= THRESHOLD;
      const br = at(column + 1, row + 1) >= THRESHOLD;
      const bl = at(column, row + 1) >= THRESHOLD;
      const top = () => crossingOn(column, row, column + 1, row);
      const right = () => crossingOn(column + 1, row, column + 1, row + 1);
      const bottom = () => crossingOn(column, row + 1, column + 1, row + 1);
      const left = () => crossingOn(column, row, column, row + 1);
      const sides = [
        tl !== tr && top,
        tr !== br && right,
        br !== bl && bottom,
        bl !== tl && left,
      ].filter(Boolean) as (() => string)[];
      if (sides.length === 2) {
        link(sides[0](), sides[1]());
      } else if (sides.length === 4) {
        const centre =
          (at(column, row) +
            at(column + 1, row) +
            at(column + 1, row + 1) +
            at(column, row + 1)) /
          4;
        // A saddle: join the corners that agree with the centre.
        if (centre >= THRESHOLD === tl) {
          link(top(), right());
          link(bottom(), left());
        } else {
          link(top(), left());
          link(bottom(), right());
        }
      }
    }
  }

  const loops: Point[][] = [];
  const visited = new Set<string>();
  for (const start of links.keys()) {
    if (visited.has(start)) continue;
    const loop: Point[] = [];
    let previous: string | null = null;
    let current: string | undefined = start;
    while (current && !visited.has(current)) {
      visited.add(current);
      loop.push(crossings.get(current) as Point);
      const next: string | undefined = (links.get(current) ?? []).find(
        (key) => key !== previous && !visited.has(key)
      );
      previous = current;
      current = next;
    }
    if (loop.length >= 3) loops.push(loop);
  }

  // A hole is worth drawing only when it holds an outsider; a gap the field
  // left between two arms of the shape is still inside the perimeter.
  const centres = outsiders.map((rect) => ({
    x: (rect.x1 + rect.x2) / 2,
    y: (rect.y1 + rect.y2) / 2,
  }));
  return loops.filter((loop, index) => {
    const others = loops.filter((_, other) => other !== index);
    const hole = insideContour(loop[0], others);
    return !hole || centres.some((centre) => insideContour(centre, [loop]));
  });
}

/** Whether `point` is inside the outline, holes excluded. */
export function insideContour(point: Point, loops: Point[][]) {
  let inside = false;
  for (const polygon of loops) {
    for (let i = 0, j = polygon.length - 1; i < polygon.length; j = i++) {
      const a = polygon[i];
      const b = polygon[j];
      if (
        a.y > point.y !== b.y > point.y &&
        point.x < ((b.x - a.x) * (point.y - a.y)) / (b.y - a.y) + a.x
      ) {
        inside = !inside;
      }
    }
  }
  return inside;
}
