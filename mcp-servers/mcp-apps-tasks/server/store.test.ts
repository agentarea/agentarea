import { Database } from "bun:sqlite";
import { describe, expect, test } from "bun:test";
import { MIGRATIONS } from "./db.ts";
import { TasksStore } from "./store.ts";

function emptyDb(): Database {
  const db = new Database(":memory:");
  for (const migrate of MIGRATIONS) migrate(db);
  return db;
}

const team = {
  people: [
    { name: "Artem Astapenko", handle: "artem", title: "CEO" },
    { name: "Sales Agent", handle: "sales-bot", kind: "agent" as const },
  ],
  viewer: "artem",
  projects: [{ key: "ops", name: "Operations", lead: "artem" }],
};

describe("setup", () => {
  test("an empty store has no tracker until setup writes one", () => {
    const db = emptyDb();
    expect(TasksStore.loadIfSetUp(db)).toBeNull();
    TasksStore.setup(db, team);
    const store = TasksStore.loadIfSetUp(db)!;
    expect(store.person("me").handle).toBe("artem");
    expect(store.person("sales-bot").kind).toBe("agent");
    expect(store.project("OPS").leadId).toBe(store.person("artem").id);
  });

  test("the first issue of a new project is number 1", () => {
    const db = emptyDb();
    TasksStore.setup(db, team);
    db.transaction(() => {
      const store = TasksStore.load(db);
      expect(store.create("OPS", { title: "Hire a designer", assignee: "sales-bot" }).key).toBe("OPS-1");
      store.save(db);
    })();
    expect(TasksStore.load(db).issue("OPS-1").assigneeId).toBe(TasksStore.load(db).person("sales-bot").id);
  });

  test("setup runs once", () => {
    const db = emptyDb();
    TasksStore.setup(db, team);
    expect(() => TasksStore.setup(db, team)).toThrow("already set up");
  });

  test("the viewer must be one of the people", () => {
    expect(() => TasksStore.setup(emptyDb(), { ...team, viewer: "nobody" })).toThrow('No person "nobody"');
    expect(() => TasksStore.setup(emptyDb(), { ...team, viewer: "me" })).toThrow("name the person by handle");
  });
});

describe("people and projects", () => {
  test("handles and project keys are unique", () => {
    const db = emptyDb();
    const store = TasksStore.setup(db, team);
    expect(() => store.addPerson({ name: "Other Artem", handle: "@Artem" })).toThrow("taken");
    expect(() => store.createProject({ key: "OPS", name: "Again", lead: "artem" })).toThrow("taken");
  });

  test("reserved and malformed values are refused", () => {
    const store = TasksStore.setup(emptyDb(), team);
    expect(() => store.addPerson({ name: "Me", handle: "me" })).toThrow("reserved");
    expect(() => store.addPerson({ name: "Space", handle: "two words" })).toThrow("not a handle");
    expect(() => store.createProject({ key: "1X", name: "Bad", lead: "artem" })).toThrow("not a project key");
  });

  test("a person added later gets the next id and can lead a project", () => {
    const db = emptyDb();
    TasksStore.setup(db, team);
    db.transaction(() => {
      const store = TasksStore.load(db);
      expect(store.addPerson({ name: "Ivan Petrov", handle: "ivan" }).id).toBe("usr_03");
      store.createProject({ key: "SALES", name: "Sales", lead: "ivan" });
      store.save(db);
    })();
    expect(TasksStore.load(db).project("sales").leadId).toBe("usr_03");
  });
});
