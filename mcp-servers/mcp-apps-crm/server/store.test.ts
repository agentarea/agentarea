import { Database } from "bun:sqlite";
import { describe, expect, test } from "bun:test";
import { MIGRATIONS } from "./db.ts";
import { CrmStore } from "./store.ts";

function emptyDb(): Database {
  const db = new Database(":memory:");
  for (const migrate of MIGRATIONS) migrate(db);
  return db;
}

const setup = {
  account: "Constractio",
  baseCurrency: "RUB" as const,
  usdRate: 92,
  owners: [{ name: "Artem Astapenko", email: "artem@constract.io" }, { name: "Sales Agent", kind: "agent" as const }],
};

describe("setup", () => {
  test("an empty store has no CRM until setup writes one", () => {
    const db = emptyDb();
    expect(CrmStore.loadIfSetUp(db)).toBeNull();
    CrmStore.setup(db, setup);
    const store = CrmStore.loadIfSetUp(db)!;
    expect(store.data.account).toEqual({ name: "Constractio", baseCurrency: "RUB" });
    expect(store.data.fxRates).toEqual({ RUB: 1, USD: 92 });
    expect(store.data.owners.map((o) => [o.id, o.kind])).toEqual([["own_01", "human"], ["own_02", "agent"]]);
  });

  test("the pipeline is the open stages in order, closed by Won and Lost", () => {
    const store = CrmStore.setup(emptyDb(), { ...setup, stages: ["Заявка", "Замер", "Смета"] });
    const stages = store.data.pipelines[0].stages;
    expect(stages.map((s) => s.name)).toEqual(["Заявка", "Замер", "Смета", "Won", "Lost"]);
    expect(stages.map((s) => s.probability)).toEqual([0.25, 0.5, 0.75, 1, 0]);
    expect(stages.map((s) => s.outcome)).toEqual([null, null, null, "won", "lost"]);
  });

  test("a USD account values a ruble at the inverse rate", () => {
    expect(CrmStore.setup(emptyDb(), { ...setup, baseCurrency: "USD", usdRate: 80 }).data.fxRates).toEqual({ RUB: 1 / 80, USD: 1 });
  });

  test("a deal can be created right after setup", () => {
    const db = emptyDb();
    CrmStore.setup(db, setup);
    db.transaction(() => {
      const store = CrmStore.load(db);
      store.createDeal({ title: "Pilot", value: 300000, ownerId: "own_02" });
      store.save(db);
    })();
    const deal = CrmStore.load(db).data.deals[0];
    expect([deal.title, deal.stageId, deal.ownerId]).toEqual(["Pilot", "stage_1", "own_02"]);
  });

  test("setup runs once and refuses a CRM without owners", () => {
    const db = emptyDb();
    CrmStore.setup(db, setup);
    expect(() => CrmStore.setup(db, setup)).toThrow("already set up");
    expect(() => CrmStore.setup(emptyDb(), { ...setup, owners: [] })).toThrow("at least one owner");
  });
});

describe("owners", () => {
  test("an owner added later gets the next id; emails stay unique", () => {
    const store = CrmStore.setup(emptyDb(), setup);
    expect(store.addOwner({ name: "Ivan Petrov" }).id).toBe("own_03");
    expect(() => store.addOwner({ name: "Twin", email: "ARTEM@constract.io" })).toThrow("already exists");
  });
});
