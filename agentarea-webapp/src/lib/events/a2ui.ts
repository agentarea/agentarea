/**
 * A2UI surface accumulation for the canonical event reducer.
 *
 * A2UI surfaces (agent-to-user interactive UI, protocol v0.9) are not a single
 * superseding payload like other parts: a create event seeds a surface, then
 * update-components upserts nodes (flat adjacency-list) and update-data patches
 * the data model at a JSON Pointer path, and delete removes the surface. This
 * mirrors the semantics the legacy messageAccumulator implemented, folded into
 * a stable accumulated shape keyed by surface_id.
 */

import { A2UI_CREATE, A2UI_UPDATE_COMPONENTS, EventData } from "./contract";

export interface A2UIComponentNode {
  id: string;
  [key: string]: unknown;
}

/** Accumulated A2UI surface state carried on an a2ui part's data. */
export interface A2UISurfaceState {
  surface_id: string;
  catalog_id: string;
  theme?: Record<string, unknown>;
  send_data_model: boolean;
  components: Record<string, A2UIComponentNode>;
  dataModel: Record<string, unknown>;
}

const DEFAULT_CATALOG =
  "https://a2ui.org/specification/v0_9/basic_catalog.json";

function asRecord(value: unknown): Record<string, unknown> {
  return value && typeof value === "object"
    ? (value as Record<string, unknown>)
    : {};
}

function asComponentArray(value: unknown): A2UIComponentNode[] {
  if (!Array.isArray(value)) return [];
  return value.filter(
    (c): c is A2UIComponentNode =>
      !!c && typeof c === "object" && typeof (c as { id?: unknown }).id === "string"
  );
}

/** Seed a fresh surface state from a create event's data. */
function seedSurface(surfaceId: string, data: EventData): A2UISurfaceState {
  return {
    surface_id: surfaceId,
    catalog_id:
      typeof data.catalog_id === "string" ? data.catalog_id : DEFAULT_CATALOG,
    theme: data.theme ? asRecord(data.theme) : undefined,
    send_data_model: data.send_data_model === true,
    components: {},
    dataModel: {},
  };
}

/**
 * Fold one A2UI event onto the current surface state (or null when none yet).
 * create seeds/replaces; update-components upserts; update-data patches the data
 * model at a JSON Pointer path. Returns the next surface state.
 */
export function applyA2UI(
  prev: A2UISurfaceState | null,
  canonical: string,
  surfaceId: string,
  data: EventData
): A2UISurfaceState {
  if (canonical === A2UI_CREATE || prev === null) {
    const base =
      prev && canonical !== A2UI_CREATE ? prev : seedSurface(surfaceId, data);
    if (canonical === A2UI_CREATE) return base;
    // Fall through to apply the update onto the freshly seeded surface.
    return applyUpdate(base, canonical, data);
  }
  return applyUpdate(prev, canonical, data);
}

function applyUpdate(
  surface: A2UISurfaceState,
  canonical: string,
  data: EventData
): A2UISurfaceState {
  if (canonical === A2UI_UPDATE_COMPONENTS) {
    const components = asComponentArray(data.components);
    if (components.length === 0) return surface;
    const next = { ...surface.components };
    for (const c of components) next[c.id] = c;
    return { ...surface, components: next };
  }
  // update-data: patch the data model at a JSON Pointer path.
  const path = typeof data.path === "string" ? data.path : "/";
  const model = { ...surface.dataModel };
  applyJsonPointer(model, path, data.value);
  return { ...surface, dataModel: model };
}

/** Strip the A2UI delimiter and everything after it from streaming content. */
const A2UI_DELIMITER = "---a2ui_JSON---";

export function stripA2UIFromStreamingContent(content: string): string {
  const idx = content.indexOf(A2UI_DELIMITER);
  if (idx === -1) return content;
  return content.substring(0, idx).trimEnd();
}

/** Apply a JSON Pointer (RFC 6901) write to a plain object (shallow, in-place). */
function applyJsonPointer(
  obj: Record<string, unknown>,
  pointer: string,
  value: unknown
): void {
  if (pointer === "/" || pointer === "") {
    Object.assign(obj, value ?? {});
    return;
  }
  const parts = pointer
    .replace(/^\//, "")
    .split("/")
    .map((p) => p.replace(/~1/g, "/").replace(/~0/g, "~"));
  let target = obj;
  for (let i = 0; i < parts.length - 1; i++) {
    let next = target[parts[i]];
    if (next == null || typeof next !== "object") {
      next = {};
      target[parts[i]] = next;
    }
    target = next as Record<string, unknown>;
  }
  const last = parts[parts.length - 1];
  if (value === undefined) {
    delete target[last];
  } else {
    target[last] = value;
  }
}
