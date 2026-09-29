import { describe, expect, it } from "vitest";
import { pageHref, pageWindow, parsePageParam, takePage } from "./offsetPage";

describe("parsePageParam", () => {
  it("is the first page when the URL names none", () => {
    expect(parsePageParam(undefined)).toBe(1);
  });

  it("reads a positive page number", () => {
    expect(parsePageParam("3")).toBe(3);
  });

  it("rejects what is not a page, rather than quietly showing page 1", () => {
    expect(parsePageParam("0")).toBeNull();
    expect(parsePageParam("-2")).toBeNull();
    expect(parsePageParam("2.5")).toBeNull();
    expect(parsePageParam("two")).toBeNull();
    expect(parsePageParam(["1", "2"])).toBeNull();
  });
});

describe("pageWindow", () => {
  it("asks for one row past the page, to learn whether another follows", () => {
    expect(pageWindow(1, 50)).toEqual({ limit: 51, offset: 0 });
    expect(pageWindow(3, 50)).toEqual({ limit: 51, offset: 100 });
  });
});

describe("takePage", () => {
  it("keeps the page and reports the extra row as a next page", () => {
    expect(takePage([1, 2, 3], 2)).toEqual({ rows: [1, 2], hasNext: true });
  });

  it("reports no next page when the extra row did not come back", () => {
    expect(takePage([1, 2], 2)).toEqual({ rows: [1, 2], hasNext: false });
    expect(takePage([1], 2)).toEqual({ rows: [1], hasNext: false });
  });
});

describe("pageHref", () => {
  it("keeps the other filters and sets the page", () => {
    expect(
      pageHref("/tasks", { status: "failed", search: "lead", page: "1" }, 2)
    ).toBe("/tasks?status=failed&search=lead&page=2");
  });

  it("drops the page parameter for the first page", () => {
    expect(pageHref("/tasks", { status: "failed", page: "3" }, 1)).toBe(
      "/tasks?status=failed"
    );
    expect(pageHref("/tasks", {}, 1)).toBe("/tasks");
  });

  it("skips empty and repeated parameters it cannot carry as one value", () => {
    expect(
      pageHref(
        "/tasks",
        { search: "", tab: ["grid", "table"], status: undefined },
        2
      )
    ).toBe("/tasks?page=2");
  });
});
