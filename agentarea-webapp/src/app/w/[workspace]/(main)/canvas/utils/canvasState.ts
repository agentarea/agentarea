import { getTaskStatusPresentation } from "@/lib/status";

export type FeedKind = "active" | "attention";
export type TableSource = "tasks" | "agentSpend";
/** Where work enters the organisation. */
export type OrgSource =
  | "event"
  | "schedule"
  | "webhook"
  | "manual"
  | "delegation"
  | "a2a";

export type TileFrame = { x: number; y: number; width: number; height: number };
export type Point = { x: number; y: number };

export type Tile =
  | { id: string; kind: "app"; appId: string; frame: TileFrame }
  | {
      id: string;
      kind: "task";
      taskId: string;
      agentId: string;
      title: string;
      frame: TileFrame;
    }
  | { id: string; kind: "feed"; feed: FeedKind; frame: TileFrame }
  | { id: string; kind: "note"; text: string; frame: TileFrame }
  | { id: string; kind: "table"; source: TableSource; frame: TileFrame }
  | { id: string; kind: "source"; source: OrgSource; frame: TileFrame }
  | { id: string; kind: "agent"; agentId: string; frame: TileFrame }
  | { id: string; kind: "connection"; connectionId: string; frame: TileFrame }
  | { id: string; kind: "activity"; frame: TileFrame };

export type TileKind = Tile["kind"];

/** An arrow between two tiles, with an optional comment on it. */
export type Link = { id: string; from: string; to: string; label: string };

type WithoutPlacement<T> = T extends unknown ? Omit<T, "id" | "frame"> : never;
export type TileInput = WithoutPlacement<Tile>;

export type Canvas = {
  id: string;
  title: string;
  tiles: Tile[];
  links: Link[];
};
export type CanvasStore = { activeId: string; canvases: Canvas[] };

export const TILE_SIZE: Record<TileKind, { width: number; height: number }> = {
  app: { width: 640, height: 440 },
  task: { width: 440, height: 540 },
  feed: { width: 320, height: 380 },
  note: { width: 260, height: 150 },
  table: { width: 720, height: 380 },
  source: { width: 300, height: 190 },
  agent: { width: 320, height: 120 },
  connection: { width: 280, height: 96 },
  activity: { width: 380, height: 560 },
};

export const GAP = 40;
const FEED_KINDS: ReadonlySet<string> = new Set(["active", "attention"]);
const TABLE_SOURCES: ReadonlySet<string> = new Set(["tasks", "agentSpend"]);
export const ORG_SOURCES: readonly OrgSource[] = [
  "event",
  "schedule",
  "webhook",
  "manual",
  "delegation",
  "a2a",
];
const ORG_SOURCE_SET: ReadonlySet<string> = new Set(ORG_SOURCES);

/** A tile of its kind's size, centred on `at`. */
export function placeTile(input: TileInput, id: string, at: Point): Tile {
  const size = TILE_SIZE[input.kind];
  return {
    ...input,
    id,
    frame: {
      x: Math.round(at.x - size.width / 2),
      y: Math.round(at.y - size.height / 2),
      ...size,
    },
  } as Tile;
}

/** A tile with its top-left corner at `at`, of `size` or its kind's size. */
export function tileAt(
  input: TileInput,
  id: string,
  at: Point,
  size: { width: number; height: number } = TILE_SIZE[input.kind]
): Tile {
  return { ...input, id, frame: { x: at.x, y: at.y, ...size } } as Tile;
}

function overlaps(a: TileFrame, b: TileFrame): boolean {
  return (
    a.x < b.x + b.width &&
    b.x < a.x + a.width &&
    a.y < b.y + b.height &&
    b.y < a.y + a.height
  );
}

/**
 * `tile` moved right in steps until it covers none of `others`, so a new tile
 * never lands on top of one already there.
 */
export function clearOf(tile: Tile, others: Tile[]): Tile {
  let frame = tile.frame;
  for (let step = 0; step < 50; step++) {
    const blocker = others.find((other) => overlaps(frame, other.frame));
    if (!blocker) break;
    frame = { ...frame, x: blocker.frame.x + blocker.frame.width + GAP };
  }
  return frame === tile.frame ? tile : { ...tile, frame };
}

/** The point to centre a tile on so it lands just right of `frame`. */
export function besideFrame(frame: TileFrame, kind: TileKind): Point {
  const size = TILE_SIZE[kind];
  return {
    x: frame.x + frame.width + GAP + size.width / 2,
    y: frame.y + size.height / 2,
  };
}

function mapCanvas(
  store: CanvasStore,
  canvasId: string,
  update: (canvas: Canvas) => Canvas
): CanvasStore {
  return {
    ...store,
    canvases: store.canvases.map((canvas) =>
      canvas.id === canvasId ? update(canvas) : canvas
    ),
  };
}

export function activeCanvas(store: CanvasStore): Canvas {
  return (
    store.canvases.find((canvas) => canvas.id === store.activeId) ??
    store.canvases[0]
  );
}

/** Adds the tile, moved clear of the tiles already on the canvas. */
export function addTile(
  store: CanvasStore,
  canvasId: string,
  tile: Tile
): CanvasStore {
  return mapCanvas(store, canvasId, (canvas) => ({
    ...canvas,
    tiles: [...canvas.tiles, clearOf(tile, canvas.tiles)],
  }));
}

/** Removes the tile and every arrow that touches it. */
export function removeTile(
  store: CanvasStore,
  canvasId: string,
  tileId: string
): CanvasStore {
  return mapCanvas(store, canvasId, (canvas) => ({
    ...canvas,
    tiles: canvas.tiles.filter((tile) => tile.id !== tileId),
    links: canvas.links.filter(
      (link) => link.from !== tileId && link.to !== tileId
    ),
  }));
}

export function setNoteText(
  store: CanvasStore,
  canvasId: string,
  tileId: string,
  text: string
): CanvasStore {
  return mapCanvas(store, canvasId, (canvas) => ({
    ...canvas,
    tiles: canvas.tiles.map((tile) =>
      tile.id === tileId && tile.kind === "note" ? { ...tile, text } : tile
    ),
  }));
}

export function setFrames(
  store: CanvasStore,
  canvasId: string,
  frames: Record<string, TileFrame>
): CanvasStore {
  return mapCanvas(store, canvasId, (canvas) => ({
    ...canvas,
    tiles: canvas.tiles.map((tile) =>
      frames[tile.id] && isFrame(frames[tile.id])
        ? { ...tile, frame: frames[tile.id] }
        : tile
    ),
  }));
}

/** Adds an arrow; a second arrow between the same two tiles is not added. */
export function addLink(
  store: CanvasStore,
  canvasId: string,
  link: Link
): CanvasStore {
  return mapCanvas(store, canvasId, (canvas) => {
    if (link.from === link.to) return canvas;
    const ids = new Set(canvas.tiles.map((tile) => tile.id));
    if (!ids.has(link.from) || !ids.has(link.to)) return canvas;
    const duplicate = canvas.links.some(
      (other) => other.from === link.from && other.to === link.to
    );
    return duplicate ? canvas : { ...canvas, links: [...canvas.links, link] };
  });
}

export function setLinkLabel(
  store: CanvasStore,
  canvasId: string,
  linkId: string,
  label: string
): CanvasStore {
  return mapCanvas(store, canvasId, (canvas) => ({
    ...canvas,
    links: canvas.links.map((link) =>
      link.id === linkId ? { ...link, label: label.trim() } : link
    ),
  }));
}

export function removeLink(
  store: CanvasStore,
  canvasId: string,
  linkId: string
): CanvasStore {
  return mapCanvas(store, canvasId, (canvas) => ({
    ...canvas,
    links: canvas.links.filter((link) => link.id !== linkId),
  }));
}

export function createCanvas(
  store: CanvasStore,
  id: string,
  title: string,
  content: Pick<Canvas, "tiles" | "links"> = { tiles: [], links: [] }
): CanvasStore {
  return {
    activeId: id,
    canvases: [...store.canvases, { id, title, ...content }],
  };
}

export function renameCanvas(
  store: CanvasStore,
  canvasId: string,
  title: string
): CanvasStore {
  const trimmed = title.trim();
  if (!trimmed) return store;
  return mapCanvas(store, canvasId, (canvas) => ({
    ...canvas,
    title: trimmed,
  }));
}

/** The last canvas stays: a store always has one to show. */
export function deleteCanvas(
  store: CanvasStore,
  canvasId: string
): CanvasStore {
  if (store.canvases.length <= 1) return store;
  const index = store.canvases.findIndex((canvas) => canvas.id === canvasId);
  if (index === -1) return store;
  const canvases = store.canvases.filter((canvas) => canvas.id !== canvasId);
  const activeId =
    store.activeId === canvasId
      ? canvases[Math.max(0, index - 1)].id
      : store.activeId;
  return { activeId, canvases };
}

export function setActive(store: CanvasStore, canvasId: string): CanvasStore {
  return store.canvases.some((canvas) => canvas.id === canvasId)
    ? { ...store, activeId: canvasId }
    : store;
}

/**
 * Apps as a bento board: the first app large, the next two stacked beside it,
 * the rest in a row underneath; the "running now" feed and the tasks table in
 * a column on the right, and a note pointing at the large app.
 */
export function appBoard(options: {
  appIds: string[];
  newId: () => string;
  note: string;
  noteLink: string;
  tableLink: string;
}): Pick<Canvas, "tiles" | "links"> {
  const { appIds, newId, note, noteLink, tableLink } = options;
  const hero = { width: 900, height: 620 };
  const side = { width: 560, height: (hero.height - GAP) / 2 };
  const row = { width: 600, height: 440 };
  const tiles: Tile[] = [];

  appIds.forEach((appId, index) => {
    const input: TileInput = { kind: "app", appId };
    if (index === 0) {
      tiles.push(tileAt(input, newId(), { x: 0, y: 0 }, hero));
    } else if (index <= 2) {
      tiles.push(
        tileAt(
          input,
          newId(),
          { x: hero.width + GAP, y: (index - 1) * (side.height + GAP) },
          side
        )
      );
    } else {
      tiles.push(
        tileAt(
          input,
          newId(),
          { x: (index - 3) * (row.width + GAP), y: hero.height + GAP },
          row
        )
      );
    }
  });

  const rightX = appIds.length === 0 ? 0 : hero.width + side.width + GAP * 2;
  const feed = tileAt(
    { kind: "feed", feed: "active" },
    newId(),
    { x: rightX, y: 0 },
    { width: 560, height: 260 }
  );
  const table = tileAt(
    { kind: "table", source: "tasks" },
    newId(),
    { x: rightX, y: 260 + GAP },
    { width: 560, height: 320 }
  );
  tiles.push(feed, table);

  const links: Link[] = [
    { id: newId(), from: feed.id, to: table.id, label: tableLink },
  ];
  if (appIds.length > 0) {
    const noteTile = tileAt({ kind: "note", text: note }, newId(), {
      x: -TILE_SIZE.note.width - GAP * 3,
      y: 60,
    });
    links.push({
      id: newId(),
      from: noteTile.id,
      to: tiles[0].id,
      label: noteLink,
    });
    tiles.push(noteTile);
  }
  return { tiles, links };
}

/** The tasks a feed tile lists: the ones running now, or the ones waiting on a person. */
export function feedTasks<T extends { status: string }>(
  tasks: T[],
  feed: FeedKind
): T[] {
  return tasks.filter((task) => {
    const kind = getTaskStatusPresentation(task.status).kind;
    return feed === "active"
      ? kind === "running" || kind === "queued"
      : kind === "attention";
  });
}

/**
 * A stored store, or null when there is none or it cannot be read back. Tiles
 * that do not parse are dropped rather than failing the whole canvas, and so
 * are arrows whose ends are gone.
 */
export function parseStore(raw: unknown): CanvasStore | null {
  if (!isRecord(raw) || !Array.isArray(raw.canvases)) return null;
  const canvases = raw.canvases.flatMap((canvas): Canvas[] => {
    if (
      !isRecord(canvas) ||
      typeof canvas.id !== "string" ||
      typeof canvas.title !== "string" ||
      !Array.isArray(canvas.tiles)
    ) {
      return [];
    }
    const tiles = canvas.tiles.flatMap((tile) => (isTile(tile) ? [tile] : []));
    const ids = new Set(tiles.map((tile) => tile.id));
    const links = (Array.isArray(canvas.links) ? canvas.links : []).flatMap(
      (link): Link[] =>
        isLink(link) && ids.has(link.from) && ids.has(link.to) ? [link] : []
    );
    return [{ id: canvas.id, title: canvas.title, tiles, links }];
  });
  if (canvases.length === 0) return null;
  const activeId =
    typeof raw.activeId === "string" &&
    canvases.some((canvas) => canvas.id === raw.activeId)
      ? raw.activeId
      : canvases[0].id;
  return { activeId, canvases };
}

function isRecord(value: unknown): value is Record<string, unknown> {
  return Boolean(value) && typeof value === "object" && !Array.isArray(value);
}

function isFrame(value: unknown): value is TileFrame {
  if (!isRecord(value)) return false;
  return ["x", "y", "width", "height"].every(
    (key) => typeof value[key] === "number" && Number.isFinite(value[key])
  );
}

function isLink(value: unknown): value is Link {
  return (
    isRecord(value) &&
    typeof value.id === "string" &&
    typeof value.from === "string" &&
    typeof value.to === "string" &&
    typeof value.label === "string"
  );
}

function isTile(value: unknown): value is Tile {
  if (!isRecord(value) || typeof value.id !== "string") return false;
  if (!isFrame(value.frame)) return false;
  switch (value.kind) {
    case "app":
      return typeof value.appId === "string";
    case "task":
      return (
        typeof value.taskId === "string" &&
        typeof value.agentId === "string" &&
        typeof value.title === "string"
      );
    case "feed":
      return typeof value.feed === "string" && FEED_KINDS.has(value.feed);
    case "note":
      return typeof value.text === "string";
    case "table":
      return (
        typeof value.source === "string" && TABLE_SOURCES.has(value.source)
      );
    case "source":
      return (
        typeof value.source === "string" && ORG_SOURCE_SET.has(value.source)
      );
    case "agent":
      return typeof value.agentId === "string";
    case "connection":
      return typeof value.connectionId === "string";
    case "activity":
      return true;
    default:
      return false;
  }
}
