import { describe, expect, it } from "vitest";
import {
  actionsFor,
  auditFiltersKey,
  auditQuery,
  isFiltered,
  parseAuditFilters,
} from "./auditFilters";

describe("parseAuditFilters", () => {
  it("keeps what the audit trail knows and drops the rest", () => {
    expect(
      parseAuditFilters({
        resource: "secret",
        action: "secret.rotate",
        actor: "user-1",
        period: "7d",
      })
    ).toEqual({
      resource: "secret",
      action: "secret.rotate",
      actor: "user-1",
      period: "7d",
      since: undefined,
      until: undefined,
    });
    expect(
      parseAuditFilters(
        new URLSearchParams(
          "resource=planet&action=drop.table&period=constructor&since=soon"
        )
      )
    ).toEqual({
      resource: undefined,
      action: undefined,
      actor: undefined,
      period: undefined,
      since: undefined,
      until: undefined,
    });
  });
});

describe("auditQuery", () => {
  const now = Date.parse("2026-10-06T12:00:00.000Z");

  it("turns a relative period into a start that ends now", () => {
    expect(
      auditQuery({ period: "24h", until: "2026-10-01T00:00:00.000Z" }, now)
    ).toEqual({
      resource_type: undefined,
      action: undefined,
      actor_id: undefined,
      since: "2026-10-05T12:00:00.000Z",
      until: undefined,
    });
  });

  it("passes a custom range through as it was picked", () => {
    expect(
      auditQuery(
        {
          since: "2026-09-30T21:00:00.000Z",
          until: "2026-10-01T20:59:59.999Z",
        },
        now
      )
    ).toMatchObject({
      since: "2026-09-30T21:00:00.000Z",
      until: "2026-10-01T20:59:59.999Z",
    });
  });
});

describe("isFiltered / auditFiltersKey", () => {
  it("tells an empty filter set from any narrowed one", () => {
    expect(isFiltered({})).toBe(false);
    expect(isFiltered({ actor: "user-1" })).toBe(true);
    expect(auditFiltersKey({ actor: "user-1" })).not.toBe(auditFiltersKey({}));
  });
});

describe("actionsFor", () => {
  it("offers only the actions about the picked resource", () => {
    expect(actionsFor("secret")).toEqual([
      "secret.create",
      "secret.update",
      "secret.rotate",
      "secret.delete",
    ]);
    expect(actionsFor("access_grant")).toEqual([
      "access.grant",
      "access.revoke",
    ]);
  });

  it("offers everything when the resource narrows nothing", () => {
    expect(actionsFor().length).toBe(actionsFor("client").length);
    expect(actionsFor().length).toBeGreaterThan(30);
  });
});
