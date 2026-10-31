import { Database } from "bun:sqlite";
import { describe, expect, test } from "bun:test";
import { headPosition, readEvents } from "@kit/events/log.ts";
import type { EventType } from "@kit/events/protocol.ts";
import { MIGRATIONS } from "./db.ts";
import {
  CONTACT_CREATED,
  contactCreated,
  DEAL_ASSIGNED,
  DEAL_CREATED,
  DEAL_STAGE_CHANGED,
  dealAssigned,
  dealCreated,
  dealStageChanged,
} from "./events.ts";
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

describe("owner handles", () => {
  test("an owner gets a handle from the email, else the name; refs accept id, handle or name", () => {
    const store = CrmStore.setup(emptyDb(), setup);
    expect(store.data.owners.map((o) => o.handle)).toEqual(["artem", "sales-agent"]);
    expect(store.addOwner({ name: "Ivan Petrov", handle: "@Ivan" }).handle).toBe("ivan");
    expect(store.addOwner({ name: "Артём", email: "artem@other.ru" }).handle).toBe("artem-2");
    expect(store.addOwner({ name: "Мария" }).handle).toBe("owner");
    expect(["own_02", "Sales-Agent", "@sales-agent", "sales agent"].map((ref) => store.owner(ref).id)).toEqual([
      "own_02", "own_02", "own_02", "own_02",
    ]);
    expect(() => store.owner("nobody")).toThrow('No owner "nobody"');
    expect(() => store.owner("me")).toThrow("no caller context");
  });

  test("handles are unique, well-formed and never \"me\"", () => {
    const store = CrmStore.setup(emptyDb(), setup);
    expect(() => store.addOwner({ name: "Other", handle: "ARTEM" })).toThrow("taken");
    expect(() => store.addOwner({ name: "Me", handle: "me" })).toThrow("reserved");
    expect(() => store.addOwner({ name: "Space", handle: "two words" })).toThrow("not a handle");
  });

  test("the migration gives owners who had none unique handles", () => {
    const db = new Database(":memory:");
    MIGRATIONS[0]!(db);
    const insert = db.query("INSERT INTO owners (id, name, title, email, kind) VALUES (?, ?, '', ?, ?)");
    insert.run("own_01", "Anna Sokolova", "anna@meridian.ru", "human");
    insert.run("own_02", "Anna Belova", "Anna@partner.ru", "human");
    insert.run("own_03", "Scout", "", "agent");
    insert.run("own_04", "Мария Иванова", "", "human");
    insert.run("own_05", "Me", "me@meridian.ru", "human");
    for (const migrate of MIGRATIONS.slice(1)) migrate(db);
    expect(db.query("SELECT id, handle, platform_id FROM owners ORDER BY id").all()).toEqual([
      { id: "own_01", handle: "anna", platform_id: null },
      { id: "own_02", handle: "anna-2", platform_id: null },
      { id: "own_03", handle: "scout", platform_id: null },
      { id: "own_04", handle: "owner", platform_id: null },
      { id: "own_05", handle: "me-2", platform_id: null },
    ]);
  });
});

describe("callers the platform names", () => {
  const maya = { kind: "user" as const, id: "6f1c2b7e-0000-4000-8000-000000000001", workspaceId: "ws-1", email: "Maya.Chen@acme.ru" };
  const bot = { kind: "agent" as const, id: "7b146d29-d8fd-45c7-8d46-91d02a8f5b06", workspaceId: "ws-1" };
  function asCaller(db: Database, caller: typeof maya | typeof bot, fn: (store: CrmStore) => void) {
    db.transaction(() => {
      const store = CrmStore.load(db);
      store.identify(caller, true);
      fn(store);
      store.save(db);
    })();
  }

  test("a new caller becomes an owner on their first change, with a handle and their identity", () => {
    const db = emptyDb();
    CrmStore.setup(db, setup);
    asCaller(db, maya, (store) => store.createDeal({ title: "Mine", value: 1000 }));
    const store = CrmStore.load(db);
    const joined = store.data.owners.find((o) => o.platformId === `user:${maya.id}`)!;
    expect([joined.id, joined.handle, joined.name, joined.email, joined.kind]).toEqual([
      "own_03", "maya.chen", "Maya.Chen@acme.ru", "Maya.Chen@acme.ru", "human",
    ]);
    expect(store.data.deals[0]!.ownerId).toBe(joined.id);
  });

  test("an agent with no email gets a handle from its id", () => {
    const db = emptyDb();
    CrmStore.setup(db, setup);
    asCaller(db, bot, (store) => store.createContact({ name: "Lead", ownerId: "me" }));
    expect(CrmStore.load(db).data.owners.find((o) => o.platformId === `agent:${bot.id}`)!.handle).toBe("agent-7b146d29");
  });

  test("a linked owner is the caller, and an email another owner has stays theirs", () => {
    const db = emptyDb();
    CrmStore.setup(db, setup);
    db.transaction(() => {
      const store = CrmStore.load(db);
      store.linkOwner("sales-agent", `agent:${bot.id}`);
      store.save(db);
    })();
    asCaller(db, bot, (store) => store.createDeal({ title: "Bot deal", value: 1, ownerId: "me" }));
    expect(CrmStore.load(db).data.deals[0]!.ownerId).toBe("own_02");
    asCaller(db, { ...maya, email: "ARTEM@constract.io" }, (store) => store.createDeal({ title: "x", value: 1 }));
    expect(CrmStore.load(db).data.owners.at(-1)!).toMatchObject({ handle: "artem-2", email: "" });
  });

  test("a read leaves an unknown caller out and refuses \"me\"; one identity is one owner", () => {
    const db = emptyDb();
    const store = CrmStore.setup(db, setup);
    store.identify(maya, false);
    expect(() => store.owner("me")).toThrow("no owner in this CRM yet");
    expect(store.data.owners).toHaveLength(2);
    store.linkOwner("artem", `user:${maya.id}`);
    expect(() => store.linkOwner("sales-agent", `user:${maya.id}`)).toThrow("already @artem");
    expect(() => store.linkOwner("artem", "maya")).toThrow("not a platform identity");
  });
});

describe("deal and contact events", () => {
  function change(db: Database, fn: (store: CrmStore) => void) {
    db.transaction(() => {
      const store = CrmStore.load(db);
      fn(store);
      store.save(db);
    })();
  }
  const events = (db: Database, name: string, after = 0) =>
    readEvents(db, { name, after, limit: 50, admits: () => true }).events.map((e) => e.data);
  const artem = { handle: "artem", name: "Artem Astapenko", kind: "human" };
  const agent = { handle: "sales-agent", name: "Sales Agent", kind: "agent" };
  const maya = { kind: "user" as const, id: "6f1c2b7e-0000-4000-8000-000000000001", workspaceId: "ws-1", email: "maya@acme.ru" };
  const mayaOwner = { handle: "maya", name: "maya@acme.ru", kind: "human" };

  function crm() {
    const db = emptyDb();
    CrmStore.setup(db, setup);
    change(db, (store) => {
      store.createCompany({ name: "Volga Logistics", ownerId: "artem" });
      store.createContact({ name: "Oleg Ivanov", companyId: "cmp_001", email: "oleg@volga.ru" });
    });
    return db;
  }

  test("a new deal is one deal.created and one deal.assigned, by the caller", () => {
    const db = crm();
    const head = headPosition(db);
    db.transaction(() => {
      const store = CrmStore.load(db);
      store.identify(maya, true);
      store.createDeal({
        title: "WMS rollout",
        value: 500000,
        companyId: "cmp_001",
        contactIds: ["ct_001"],
        ownerId: "sales-agent",
        expectedCloseDate: "2026-12-01",
        source: "Referral",
      });
      store.save(db);
    })();
    const deal = {
      dealId: "deal_001",
      title: "WMS rollout",
      value: 500000,
      currency: "RUB",
      stage: { id: "stage_1", name: "Lead in" },
      status: "open",
      company: { id: "cmp_001", name: "Volga Logistics" },
      contacts: [{ id: "ct_001", name: "Oleg Ivanov", email: "oleg@volga.ru" }],
      owner: agent,
      expectedCloseDate: "2026-12-01",
      source: "Referral",
    };
    expect(events(db, DEAL_CREATED, head)).toEqual([{ ...deal, createdBy: mayaOwner }]);
    expect(events(db, DEAL_ASSIGNED, head)).toEqual([{ ...deal, assignedBy: mayaOwner }]);
  });

  test("without a caller the record's owner is who made the change", () => {
    const db = crm();
    change(db, (store) => store.createDeal({ title: "Pilot", value: 1, ownerId: "sales-agent" }));
    expect((events(db, DEAL_CREATED)[0]!.createdBy)).toEqual(agent);
    expect(events(db, CONTACT_CREATED)).toEqual([
      {
        contactId: "ct_001",
        name: "Oleg Ivanov",
        title: "",
        email: "oleg@volga.ru",
        phone: "",
        company: { id: "cmp_001", name: "Volga Logistics" },
        owner: artem,
        createdBy: artem,
      },
    ]);
  });

  test("every stage move, win, loss and reopen is one deal.stage_changed", () => {
    const db = crm();
    change(db, (store) => store.createDeal({ title: "Pilot", value: 1, companyId: "cmp_001" }));
    change(db, (store) => store.updateDeal("deal_001", { stageId: "stage_2" }));
    change(db, (store) => store.updateDeal("deal_001", { stageId: "stage_2", value: 2 }));
    change(db, (store) => store.updateDeal("deal_001", { status: "lost", lostReason: "No budget" }));
    change(db, (store) => store.updateDeal("deal_001", { lostReason: "Price too high", status: "lost" }));
    change(db, (store) => store.updateDeal("deal_001", { status: "open" }));
    change(db, (store) => store.updateDeal("deal_001", { status: "won" }));
    const moves = events(db, DEAL_STAGE_CHANGED);
    expect(moves.map((d) => [(d.from as { id: string }).id, (d.to as { id: string }).id, d.outcome, d.lostReason])).toEqual([
      ["stage_1", "stage_2", "open", null],
      ["stage_2", "lost", "lost", "No budget"],
      ["lost", "stage_2", "open", null],
      ["stage_2", "won", "won", null],
    ]);
    expect(moves[0]).toMatchObject({ stage: { id: "stage_2", name: "Qualified" }, status: "open", value: 1, changedBy: artem });
  });

  test("reassigning a deal is a deal.assigned to the new owner; keeping the owner is none", () => {
    const db = crm();
    change(db, (store) => store.createDeal({ title: "Pilot", value: 1, companyId: "cmp_001" }));
    change(db, (store) => store.updateDeal("deal_001", { ownerId: "artem", title: "Pilot 2" }));
    change(db, (store) => store.updateDeal("deal_001", { ownerId: "Sales Agent", stageId: "stage_3" }));
    expect(events(db, DEAL_ASSIGNED).map((d) => [(d.owner as { handle: string }).handle, d.title])).toEqual([
      ["artem", "Pilot"],
      ["sales-agent", "Pilot 2"],
    ]);
    expect(events(db, DEAL_STAGE_CHANGED)[0]).toMatchObject({ owner: agent, to: { id: "stage_3" } });
  });

  test("a change that rolls back records no event", () => {
    const db = crm();
    const head = headPosition(db);
    expect(() =>
      change(db, (store) => {
        store.createContact({ name: "Doomed", companyId: "cmp_001" });
        store.createDeal({ title: "Doomed", value: 1, companyId: "cmp_001" });
        store.updateDeal("deal_001", { status: "won" });
        throw new Error("abort");
      }),
    ).toThrow("abort");
    for (const name of [DEAL_CREATED, DEAL_ASSIGNED, DEAL_STAGE_CHANGED, CONTACT_CREATED]) expect(events(db, name, head)).toEqual([]);
  });

  test("filters narrow by owner, owner kind and the stage moved into", () => {
    const admits = <A>(type: EventType<A>, raw: Record<string, unknown>, data: Record<string, unknown>) =>
      type.admits(type.parseArguments(raw), data);
    const deal = { owner: agent };
    expect(admits(dealCreated, { owner: "@Sales-Agent", ownerKind: "agent" }, deal)).toBe(true);
    expect(admits(dealCreated, { ownerKind: "human" }, deal)).toBe(false);
    expect(admits(dealAssigned, { owner: "scout" }, deal)).toBe(false);
    expect(admits(dealAssigned, { owner: "sales-agent" }, deal)).toBe(true);
    expect(admits(contactCreated, { owner: "artem" }, { owner: artem })).toBe(true);
    expect(() => contactCreated.parseArguments({ ownerKind: "human" })).toThrow('unknown argument "ownerKind"');
    expect(() => dealCreated.parseArguments({ ownerKind: "robot" })).toThrow("ownerKind is human or agent");

    const won = { ...deal, to: { id: "won", name: "Won" }, outcome: "won" };
    const qualified = { ...deal, to: { id: "stage_2", name: "Qualified" }, outcome: "open" };
    const closedAs = { ...deal, to: { id: "closed_ok", name: "Подписан" }, outcome: "won" };
    expect(admits(dealStageChanged, { stage: "WON" }, won)).toBe(true);
    expect(admits(dealStageChanged, { stage: "won" }, closedAs)).toBe(true);
    expect(admits(dealStageChanged, { stage: "подписан" }, closedAs)).toBe(true);
    expect(admits(dealStageChanged, { stage: "lost" }, won)).toBe(false);
    expect(admits(dealStageChanged, { stage: "qualified" }, qualified)).toBe(true);
    expect(admits(dealStageChanged, { stage: "stage_2", owner: "sales-agent" }, qualified)).toBe(true);
    expect(admits(dealStageChanged, { stage: "open" }, qualified)).toBe(false);
    expect(admits(dealStageChanged, { stage: "won" }, qualified)).toBe(false);
  });
});
