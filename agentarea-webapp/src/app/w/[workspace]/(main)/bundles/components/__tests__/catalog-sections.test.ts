import { describe, expect, it } from "vitest";
import { normalize, type RegistryItem } from "../catalog-data";
import {
  catalogSections,
  SECTION_SIZE,
  showsSections,
} from "../catalog-sections";

function connection(id: string, verified = false) {
  return normalize("connections", {
    id,
    name: id,
    description: null,
    version: null,
    tags: [],
    spec: verified
      ? { raw_spec: { metadata: { "agentarea:oauth_status": "verified" } } }
      : {},
  } as RegistryItem);
}

function skill(id: string, stars?: number) {
  return normalize("skills", {
    id,
    name: id,
    description: null,
    version: null,
    tags: [],
    spec: stars === undefined ? {} : { provenance: { stars } },
  } as RegistryItem);
}

const ids = (entries: { id: string }[]) => entries.map((e) => e.id);

describe("catalog shelves", () => {
  it("connections: verified first, then the rest of the recommended order", () => {
    const head = [
      connection("a"),
      connection("b", true),
      connection("c"),
      connection("d", true),
    ];
    const [recommended, popular] = catalogSections("connections", head);
    expect(ids(recommended.entries)).toEqual(["b", "d"]);
    expect(ids(popular.entries)).toEqual(["a", "c"]);
  });

  it("skills: the curated head, then the most-starred of the rest", () => {
    const curated = Array.from({ length: SECTION_SIZE }, (_, i) =>
      skill(`c${i}`, 10_000)
    );
    const head = [
      ...curated,
      skill("low", 5),
      skill("none"),
      skill("high", 900),
    ];
    const [recommended, popular] = catalogSections("skills", head);
    expect(ids(recommended.entries)).toEqual(ids(curated));
    expect(ids(popular.entries)).toEqual(["high", "low"]);
  });

  it("leaves an empty shelf out", () => {
    expect(catalogSections("agents", [skill("x")])).toEqual([]);
  });

  it("only the unfiltered catalog in recommended order gets shelves", () => {
    const base = {
      query: "",
      category: null,
      protocol: null,
      sort: "recommended",
      all: "__all__",
    };
    expect(showsSections(base)).toBe(true);
    expect(showsSections({ ...base, category: "__all__" })).toBe(true);
    expect(showsSections({ ...base, query: "sentry" })).toBe(false);
    expect(showsSections({ ...base, category: "Design" })).toBe(false);
    expect(showsSections({ ...base, sort: "name" })).toBe(false);
  });
});
