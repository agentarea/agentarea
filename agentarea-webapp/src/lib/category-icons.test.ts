import { describe, expect, it } from "vitest";
import { Bot, CircleDashed, Tag } from "lucide-react";
import { getCategoryIcon } from "./category-icons";

describe("category icons", () => {
  it("resolves the same icon however a source spells the category", () => {
    // The catalog's three sources disagree on casing and punctuation for what
    // is one concept: the MCP registry writes "Data & Analytics", skills write
    // "data", bundles write "data".
    const spellings = ["Data & Analytics", "data", "DATA", "data-analytics"];
    const icons = new Set(spellings.map((s) => getCategoryIcon(s)));

    expect(icons.size).toBe(1);
  });

  it("gives the fallback bucket its own icon in either casing", () => {
    // "other" is not a topic, so it must not look like one.
    expect(getCategoryIcon("other")).toBe(CircleDashed);
    expect(getCategoryIcon("Other")).toBe(CircleDashed);
  });

  it("reuses the entity icon where a category names an entity", () => {
    expect(getCategoryIcon("agent")).toBe(Bot);
  });

  it("falls back to one neutral icon for a category it has never seen", () => {
    // Deliberately not derived from the string: an icon picked by hash reads
    // as meaning that isn't there, and changes when the category is renamed.
    expect(getCategoryIcon("kombucha brewing")).toBe(Tag);
    expect(getCategoryIcon(undefined)).toBe(Tag);
    expect(getCategoryIcon("")).toBe(Tag);
  });

  it("covers every category the catalog actually serves", () => {
    // Values taken from registry_items.category across mcp_servers, skills and
    // bundles. A miss here is a category rendering as the generic tag.
    const live = [
      "AI & Search",
      "Communication",
      "Data & Analytics",
      "Design",
      "Engineering",
      "Finance & Commerce",
      "Marketing",
      "Productivity",
      "Sales & CRM",
      "Web & Hosting",
      "Other",
      "agent",
      "analysis",
      "creative",
      "data",
      "design",
      "development",
      "devops",
      "documents",
      "product",
      "productivity",
      "security",
      "testing",
      "other",
      "engineering",
      "finance",
      "hr",
      "marketing",
      "operations",
      "research",
      "sales",
      "support",
    ];

    const unmapped = live.filter((c) => getCategoryIcon(c) === Tag);

    expect(unmapped).toEqual([]);
  });
});
