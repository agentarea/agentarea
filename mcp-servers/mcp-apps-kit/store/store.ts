/**
 * An app's state as one sqlite database stored as one object in the
 * platform's app storage, written with optimistic concurrency.
 *
 * Storage is the single source of truth and any number of app processes may
 * share it. Each process keeps the last version it saw in memory, keyed by
 * ETag. Every read and every transaction first asks storage for the current
 * ETag and refetches the database if it moved. A transaction runs on a copy,
 * serializes the whole database and writes it back conditionally; when
 * another writer got there first the write is refused (412) and the
 * transaction runs again on the newer version.
 */
import { Database } from "bun:sqlite";
import { StorageClient, storageUrl } from "./client.ts";

/** Brings the schema from version `index` to `index + 1`; runs inside the transaction that writes it. */
export type Migration = (db: Database) => void;

export type AppStoreOptions = {
  /** Object path under the instance's storage prefix, e.g. "app.sqlite". */
  file: string;
  /** Migration `i` produces schema version `i + 1`; the schema version is `PRAGMA user_version`. */
  migrations: readonly Migration[];
  /** Demo rows, written only into a database that does not exist yet, and only with AGENTAREA_MCP_SEED_DEMO=1. */
  seed?: Migration;
  /** Defaults to `process.env`. */
  env?: Record<string, string | undefined>;
  /** Attempts per transaction before a run of conflicts is reported as an error. */
  maxAttempts?: number;
};

const CONTENT_TYPE = "application/vnd.sqlite3";
const DEFAULT_ATTEMPTS = 10;

const sleep = (ms: number) => new Promise((resolve) => setTimeout(resolve, ms));
/** Full jitter over an exponential window, capped at one second. */
const backoff = (attempt: number) => Math.random() * Math.min(1000, 20 * 2 ** attempt);

export function schemaVersion(db: Database): number {
  return (db.query("PRAGMA user_version").get() as { user_version: number }).user_version;
}

export class AppStore {
  readonly #client: StorageClient;
  readonly #file: string;
  readonly #migrations: readonly Migration[];
  readonly #seed: Migration | null;
  readonly #maxAttempts: number;

  /** Last version seen in storage; null bytes mean the object does not exist (or was never fetched). */
  #etag: string | null = null;
  #bytes: Uint8Array | null = null;
  #reader: Database | null = null;
  #version = 0;
  #queue: Promise<unknown> = Promise.resolve();
  #conflicts = 0;

  constructor(client: StorageClient, options: AppStoreOptions & { seedDemo: boolean }) {
    this.#client = client;
    this.#file = options.file;
    this.#migrations = options.migrations;
    this.#seed = options.seedDemo ? (options.seed ?? null) : null;
    this.#maxAttempts = options.maxAttempts ?? DEFAULT_ATTEMPTS;
  }

  get file(): string {
    return this.#file;
  }

  /** Schema version of the database last seen in storage. */
  get schemaVersion(): number {
    return this.#version;
  }

  /** Writes this process lost to another writer and retried. */
  get conflicts(): number {
    return this.#conflicts;
  }

  /** Runs `fn` on the current version, read-only. A missing database is created and an older one migrated first. */
  read<T>(fn: (db: Database) => T): Promise<T> {
    return this.#serial(async () => {
      await this.#refresh();
      if (this.#bytes === null || this.#version < this.#migrations.length) await this.#write(() => undefined);
      return settled(fn(this.#reader!));
    });
  }

  /**
   * Runs `fn` inside one sqlite transaction on the current version and writes the result back.
   * `fn` may run more than once (each time on a newer version), so it must be synchronous and
   * have no effects outside `db`. A throw rolls back and nothing is written.
   */
  transact<T>(fn: (db: Database) => T): Promise<T> {
    return this.#serial(() => this.#write(fn));
  }

  /** One operation at a time per process: a transaction never races a sibling in the same process. */
  #serial<T>(task: () => Promise<T>): Promise<T> {
    const run = this.#queue.then(task);
    this.#queue = run.catch(() => undefined);
    return run;
  }

  async #refresh(): Promise<void> {
    const etag = await this.#client.head(this.#file);
    if (etag === null) return this.#adopt(null, null);
    if (etag === this.#etag) return;
    const object = await this.#client.get(this.#file);
    this.#adopt(object?.bytes ?? null, object?.etag ?? null);
  }

  #adopt(bytes: Uint8Array | null, etag: string | null) {
    this.#reader?.close();
    this.#bytes = bytes;
    this.#etag = etag;
    this.#reader = bytes ? Database.deserialize(bytes, { readonly: true, strict: true }) : null;
    this.#version = this.#reader ? schemaVersion(this.#reader) : 0;
  }

  async #write<T>(fn: (db: Database) => T): Promise<T> {
    for (let attempt = 1; ; attempt++) {
      await this.#refresh();
      const known = this.#migrations.length;
      if (this.#version > known) {
        throw new Error(
          `${this.#file} has schema version ${this.#version}, newer than this app knows (${known}); ` +
            "it is open read-only and writes are refused until the app is upgraded",
        );
      }
      const creating = this.#bytes === null;
      const db = creating
        ? new Database(":memory:", { strict: true })
        : Database.deserialize(this.#bytes!, { strict: true });
      try {
        db.run("PRAGMA foreign_keys = ON");
        let migrated = false;
        const result = db.transaction(() => {
          migrated = migrate(db, this.#migrations);
          if (creating && this.#seed) this.#seed(db);
          return settled(fn(db));
        })();
        // Nothing to write back: no request to storage, no new version for other processes to fetch.
        if (!creating && !migrated && totalChanges(db) === 0) return result;
        const bytes = new Uint8Array(db.serialize());
        const precondition = creating ? ({ ifNoneMatch: "*" } as const) : { ifMatch: this.#etag! };
        const put = await this.#client.put(this.#file, bytes, precondition, CONTENT_TYPE);
        if (put.ok) {
          this.#adopt(bytes, put.etag);
          return result;
        }
      } finally {
        db.close();
      }
      this.#conflicts += 1;
      if (attempt >= this.#maxAttempts) {
        throw new Error(`${this.#file}: gave up after ${attempt} attempts, each lost to a concurrent write`);
      }
      await sleep(backoff(attempt));
    }
  }
}

function settled<T>(value: T): T {
  if (value instanceof Promise) throw new Error("A store callback must be synchronous: it can run again on retry");
  return value;
}

const totalChanges = (db: Database) => (db.query("SELECT total_changes() AS n").get() as { n: number }).n;

/** Applies the migrations the database has not had yet; true when it applied any. */
function migrate(db: Database, migrations: readonly Migration[]): boolean {
  const from = schemaVersion(db);
  if (from >= migrations.length) return false;
  for (let version = from; version < migrations.length; version++) migrations[version](db);
  db.run(`PRAGMA user_version = ${migrations.length}`);
  return true;
}

/**
 * Opens the app's database in the instance's storage, creating it (and seeding demo rows when
 * AGENTAREA_MCP_SEED_DEMO=1) if it does not exist, and migrating it if it is older than the code.
 * There is no local fallback: without storage configured the app does not start.
 */
export async function openAppStore(options: AppStoreOptions): Promise<AppStore> {
  const env = options.env ?? process.env;
  const managerUrl = env.MCP_MANAGER_URL;
  const instanceId = env.MCP_INSTANCE_ID;
  const token = env.MCP_STORAGE_TOKEN;
  const missing = [!managerUrl && "MCP_MANAGER_URL", !instanceId && "MCP_INSTANCE_ID", !token && "MCP_STORAGE_TOKEN"].filter(Boolean);
  if (missing.length > 0) {
    throw new Error(
      `${missing.join(", ")} must be set: the app keeps its state in the platform's MCP storage ` +
        "(for local runs, start it through mcp-apps-kit/store/dev-server.ts)",
    );
  }
  const base = storageUrl(managerUrl!, instanceId!);
  const store = new AppStore(new StorageClient(base, token!), { ...options, seedDemo: env.AGENTAREA_MCP_SEED_DEMO === "1" });
  await store.read(() => undefined);
  return store;
}
