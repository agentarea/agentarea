import { Database } from "bun:sqlite";
import { describe, expect, test } from "bun:test";
import { MIGRATIONS } from "./db.ts";
import { headPosition, readEvents } from "@kit/events/log.ts";
import { TASK_ASSIGNED } from "./events.ts";
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

describe("task.assigned events", () => {
  function change(db: Database, fn: (store: TasksStore) => void) {
    db.transaction(() => {
      const store = TasksStore.load(db);
      fn(store);
      store.save(db);
    })();
  }
  const assigned = (db: Database, after = 0) =>
    readEvents(db, { name: TASK_ASSIGNED, after, limit: 50, admits: () => true }).events.map((e) => e.data);

  test("creating an assigned issue records who got it, from whom, in which project", () => {
    const db = emptyDb();
    TasksStore.setup(db, team);
    change(db, (store) => store.create("OPS", { title: "Hire a designer", assignee: "sales-bot", priority: "high" }));
    expect(assigned(db)).toEqual([
      {
        key: "OPS-1",
        title: "Hire a designer",
        description: "",
        status: "todo",
        priority: "high",
        due: null,
        project: { key: "OPS", name: "Operations" },
        assignee: { handle: "sales-bot", name: "Sales Agent", kind: "agent" },
        assignedBy: { handle: "artem", name: "Artem Astapenko", kind: "human" },
      },
    ]);
  });

  test("assigning, reassigning and unassigning: an event for each new assignee only", () => {
    const db = emptyDb();
    TasksStore.setup(db, team);
    change(db, (store) => store.create("OPS", { title: "Unowned" }));
    expect(assigned(db)).toEqual([]);
    change(db, (store) => store.update("OPS-1", { assignee: "sales-bot" }));
    change(db, (store) => store.update("OPS-1", { assignee: "sales-bot", status: "in_progress" }));
    change(db, (store) => store.update("OPS-1", { assignee: "artem" }, "sales-bot"));
    change(db, (store) => store.update("OPS-1", { assignee: null }));
    expect(assigned(db).map((d) => [(d.assignee as { handle: string }).handle, (d.assignedBy as { handle: string }).handle])).toEqual([
      ["sales-bot", "artem"],
      ["artem", "sales-bot"],
    ]);
  });

  test("a change that rolls back records no event", () => {
    const db = emptyDb();
    TasksStore.setup(db, team);
    const head = headPosition(db);
    expect(() =>
      change(db, (store) => {
        store.create("OPS", { title: "Doomed", assignee: "sales-bot" });
        throw new Error("abort");
      }),
    ).toThrow("abort");
    expect(assigned(db, head)).toEqual([]);
  });
});

describe("callers the platform names", () => {
  const maya = { kind: "user" as const, id: "6f1c2b7e-0000-4000-8000-000000000001", workspaceId: "ws-1", email: "Maya.Chen@acme.ru" };
  const bot = { kind: "agent" as const, id: "7b146d29-d8fd-45c7-8d46-91d02a8f5b06", workspaceId: "ws-1" };
  function asCaller(db: Database, caller: typeof maya | typeof bot, fn: (store: TasksStore) => void) {
    db.transaction(() => {
      const store = TasksStore.load(db);
      store.identify(caller, true);
      fn(store);
      store.save(db);
    })();
  }

  test("a new caller joins the board on their first change, and the change is theirs", () => {
    const db = emptyDb();
    TasksStore.setup(db, team);
    asCaller(db, maya, (store) => store.create("OPS", { title: "Mine" }));
    const store = TasksStore.load(db);
    const joined = store.data.people.find((p) => p.platformId === `user:${maya.id}`)!;
    expect([joined.handle, joined.name, joined.kind]).toEqual(["maya.chen", "Maya.Chen@acme.ru", "human"]);
    expect(store.issue("OPS-1").creatorId).toBe(joined.id);
  });

  test("a linked person is the caller; an agent's \"me\" is itself", () => {
    const db = emptyDb();
    TasksStore.setup(db, team);
    db.transaction(() => {
      const store = TasksStore.load(db);
      store.linkPerson("sales-bot", `agent:${bot.id}`);
      store.save(db);
    })();
    asCaller(db, bot, (store) => {
      store.create("OPS", { title: "Bot work", assignee: "me" });
    });
    const issue = TasksStore.load(db).issue("OPS-1");
    const salesBot = TasksStore.load(db).person("sales-bot").id;
    expect([issue.creatorId, issue.assigneeId]).toEqual([salesBot, salesBot]);
  });

  test("a read names a known caller as the viewer and refuses \"me\" for an unknown one", () => {
    const db = emptyDb();
    TasksStore.setup(db, team);
    const store = TasksStore.load(db);
    store.identify(maya, false);
    expect(() => store.person("me")).toThrow("not on this board yet");
    expect(store.viewerId).toBe(store.data.viewerId);
  });

  test("one identity is one person", () => {
    const db = emptyDb();
    const store = TasksStore.setup(db, team);
    store.linkPerson("artem", `user:${maya.id}`);
    expect(() => store.linkPerson("sales-bot", `user:${maya.id}`)).toThrow("already @artem");
    expect(() => store.linkPerson("artem", "maya")).toThrow("not a platform identity");
  });

  test("a handle a caller would take is never reused", () => {
    const db = emptyDb();
    TasksStore.setup(db, { ...team, people: [...team.people, { name: "Other Maya", handle: "maya.chen" }] });
    asCaller(db, maya, (store) => store.create("OPS", { title: "x" }));
    expect(TasksStore.load(db).data.people.find((p) => p.platformId === `user:${maya.id}`)!.handle).toBe("maya.chen-2");
  });
});

