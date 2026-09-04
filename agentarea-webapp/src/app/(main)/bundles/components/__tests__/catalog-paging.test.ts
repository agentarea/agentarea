import { describe, expect, it } from "vitest";
import {
  canFetchMore,
  catalogPagingReducer,
  hasMore,
  initialPaging,
  type CatalogPaging,
} from "../catalog-paging";
import type { CatalogEntry } from "../catalog-data";

const entry = (id: string): CatalogEntry => ({
  id,
  type: "skills",
  title: id,
  description: "",
  tags: [],
  category: null,
  integrations: [],
  meta: [],
  iconUrl: null,
  featured: false,
  verified: false,
  installEntityId: null,
  spec: {},
});

const seeded = (ids: string[], total: number): CatalogPaging =>
  catalogPagingReducer(initialPaging(), {
    type: "seed",
    entries: ids.map(entry),
    total,
    categories: [],
  });

describe("hasMore", () => {
  it("compares what is loaded against the server's total, not the last page size", () => {
    // The old gallery inferred "more" from the length of the last page, which
    // is wrong the moment pages are merged from several registries.
    expect(hasMore(seeded(["a", "b"], 96))).toBe(true);
  });

  it("is false once every matching item is loaded", () => {
    expect(hasMore(seeded(["a", "b"], 2))).toBe(false);
  });

  it("is true when the page is empty but the catalog is not", () => {
    // ?category=other: a page whose matches all sit further in. Reporting "no
    // more" here is what killed infinite scroll and rendered "No matches".
    expect(hasMore(seeded([], 310))).toBe(true);
  });
});

describe("canFetchMore", () => {
  it("allows a fetch when there is more and nothing is in flight", () => {
    expect(canFetchMore(seeded(["a"], 10))).toBe(true);
  });

  it("blocks a second fetch while one is already in flight", () => {
    // The scroll sentinel stays inside the viewport while a short page renders,
    // so without this guard it fires page after page in a cascade.
    const busy = catalogPagingReducer(seeded(["a"], 10), { type: "appendStart" });
    expect(canFetchMore(busy)).toBe(false);
  });

  it("blocks while the first page is still loading", () => {
    const loading = catalogPagingReducer(seeded(["a"], 10), { type: "reload" });
    expect(canFetchMore(loading)).toBe(false);
  });

  it("blocks after a failure so the retry is deliberate", () => {
    const failed = catalogPagingReducer(seeded(["a"], 10), {
      type: "fail",
      error: "network",
    });
    expect(canFetchMore(failed)).toBe(false);
  });

  it("allows fetching again once the failure is retried", () => {
    const failed = catalogPagingReducer(seeded(["a"], 10), { type: "fail", error: "network" });
    expect(canFetchMore(catalogPagingReducer(failed, { type: "appendStart" }))).toBe(false);
    const retried = catalogPagingReducer(failed, {
      type: "append",
      entries: [entry("b")],
      total: 10,
      categories: [],
    });
    expect(canFetchMore(retried)).toBe(true);
  });
});

describe("append", () => {
  it("adds to the end and never reorders what is already rendered", () => {
    // The server owns the order. Re-sorting client-side spliced newly loaded
    // items into the middle of the list, jumping the content under the cursor.
    const state = catalogPagingReducer(seeded(["m", "a"], 4), {
      type: "append",
      entries: [entry("z"), entry("b")],
      total: 4,
      categories: [],
    });
    expect(state.entries.map((e) => e.id)).toEqual(["m", "a", "z", "b"]);
  });

  it("drops ids already loaded so an overlapping page cannot duplicate keys", () => {
    const state = catalogPagingReducer(seeded(["a", "b"], 4), {
      type: "append",
      entries: [entry("b"), entry("c")],
      total: 4,
      categories: [],
    });
    expect(state.entries.map((e) => e.id)).toEqual(["a", "b", "c"]);
  });

  it("takes the freshest total so the end of the catalog can move", () => {
    const state = catalogPagingReducer(seeded(["a"], 10), {
      type: "append",
      entries: [entry("b")],
      total: 2,
      categories: [],
    });
    expect(state.total).toBe(2);
    expect(hasMore(state)).toBe(false);
  });

  it("clears a previous error", () => {
    const failed = catalogPagingReducer(seeded(["a"], 10), { type: "fail", error: "network" });
    const ok = catalogPagingReducer(failed, {
      type: "append",
      entries: [entry("b")],
      total: 10,
      categories: [],
    });
    expect(ok.error).toBeNull();
  });

  it("stops paging if the server returns nothing while claiming more exists", () => {
    // Guards against an infinite loop when total and reality disagree.
    const state = catalogPagingReducer(seeded(["a"], 99), {
      type: "append",
      entries: [],
      total: 99,
      categories: [],
    });
    expect(hasMore(state)).toBe(false);
  });
});

describe("fail", () => {
  it("keeps what is already rendered", () => {
    const failed = catalogPagingReducer(seeded(["a", "b"], 10), {
      type: "fail",
      error: "network",
    });
    expect(failed.entries.map((e) => e.id)).toEqual(["a", "b"]);
    expect(failed.error).toBe("network");
  });

  it("does not declare the catalog exhausted", () => {
    // A transient failure used to set hasMore=false permanently, so one blip
    // ended infinite scroll for the rest of the session.
    const failed = catalogPagingReducer(seeded(["a"], 10), { type: "fail", error: "network" });
    expect(hasMore(failed)).toBe(true);
  });
});

describe("reload", () => {
  it("clears entries and error when the filters change", () => {
    const failed = catalogPagingReducer(seeded(["a", "b"], 10), {
      type: "fail",
      error: "network",
    });
    const reloading = catalogPagingReducer(failed, { type: "reload" });
    expect(reloading.entries).toEqual([]);
    expect(reloading.error).toBeNull();
    expect(reloading.status).toBe("loading");
  });

  it("keeps the previous facets so the sidebar does not collapse mid-switch", () => {
    const withFacets = catalogPagingReducer(initialPaging(), {
      type: "seed",
      entries: [entry("a")],
      total: 1,
      categories: [{ value: "data", count: 3 }],
    });
    expect(catalogPagingReducer(withFacets, { type: "reload" }).categories).toEqual([
      { value: "data", count: 3 },
    ]);
  });
});

describe("seed", () => {
  it("replaces everything with a fresh first page", () => {
    const state = catalogPagingReducer(seeded(["a", "b"], 10), {
      type: "seed",
      entries: [entry("x")],
      total: 1,
      categories: [{ value: "other", count: 1 }],
    });
    expect(state.entries.map((e) => e.id)).toEqual(["x"]);
    expect(state.total).toBe(1);
    expect(state.categories).toEqual([{ value: "other", count: 1 }]);
    expect(state.status).toBe("idle");
  });

  it("carries a server error through instead of pretending the catalog is empty", () => {
    const state = catalogPagingReducer(initialPaging(), {
      type: "seed",
      entries: [],
      total: 0,
      categories: [],
      error: "Failed to load catalog.",
    });
    expect(state.error).toBe("Failed to load catalog.");
  });
});
