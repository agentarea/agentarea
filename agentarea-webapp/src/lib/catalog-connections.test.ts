import { describe, expect, it } from "vitest";
import {
  existingConnectionsHref,
  fromCatalogItem,
  parseCatalogSource,
} from "./catalog-connections";

const ITEM = "0b1c5e1e-6a39-4f0f-9a43-1d0c2a6e6c11";

describe("existingConnectionsHref", () => {
  it("is nothing for an item never connected", () => {
    expect(existingConnectionsHref(ITEM, [])).toBeNull();
  });

  it("opens the one MCP connection", () => {
    expect(existingConnectionsHref(ITEM, [{ id: "i1", kind: "mcp" }])).toBe(
      "/connections/i1"
    );
  });

  it("opens the one API connection on its own page", () => {
    expect(existingConnectionsHref(ITEM, [{ id: "c1", kind: "openapi" }])).toBe(
      "/connections/openapi/c1"
    );
  });

  it("opens the list narrowed to the item when there are several", () => {
    expect(
      existingConnectionsHref(ITEM, [
        { id: "i1", kind: "mcp" },
        { id: "c1", kind: "openapi" },
      ])
    ).toBe(`/connections?source=${ITEM}`);
  });
});

describe("parseCatalogSource", () => {
  it("ignores an empty or repeated param", () => {
    expect(parseCatalogSource("")).toBeNull();
    expect(parseCatalogSource(["a", "b"])).toBeNull();
    expect(parseCatalogSource(ITEM)).toBe(ITEM);
  });
});

describe("fromCatalogItem", () => {
  it("keeps instances whose spec came from the item and API connections from it", () => {
    const result = fromCatalogItem(
      ITEM,
      [
        { id: "from-copy", server_spec_id: "spec-copy" },
        { id: "manual", server_spec_id: "spec-manual" },
        { id: "spec-not-loaded", server_spec_id: "spec-missing" },
      ],
      [
        { id: "spec-copy", registry_item_id: ITEM },
        { id: "spec-manual", registry_item_id: null },
      ],
      [
        { id: "api", registry_item_id: ITEM },
        { id: "other-api", registry_item_id: "another-item" },
        { id: "manual-api", registry_item_id: null },
      ]
    );

    expect(result.instances.map((i) => i.id)).toEqual(["from-copy"]);
    expect(result.openApiConnections.map((c) => c.id)).toEqual(["api"]);
  });
});
