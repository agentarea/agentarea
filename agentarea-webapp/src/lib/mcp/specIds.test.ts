import { describe, expect, it } from "vitest";
import { specIdBatches } from "./specIds";

const id = (n: number) => `00000000-0000-4000-8000-${String(n).padStart(12, "0")}`;

describe("specIdBatches", () => {
  it("asks once for each spec the instances use", () => {
    expect(specIdBatches([id(1), id(2), id(1)])).toEqual([[id(1), id(2)]]);
  });

  it("skips values that cannot name a spec", () => {
    expect(specIdBatches(["", "echo", null, undefined, id(3)])).toEqual([[id(3)]]);
  });

  it("splits into batches the endpoint accepts", () => {
    const ids = Array.from({ length: 5 }, (_, n) => id(n));

    expect(specIdBatches(ids, 2)).toEqual([[id(0), id(1)], [id(2), id(3)], [id(4)]]);
  });

  it("asks for nothing when there are no instances", () => {
    expect(specIdBatches([])).toEqual([]);
  });
});
