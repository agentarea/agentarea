import fs from "node:fs/promises";
import path from "node:path";
import type { Contact, OutreachData, Reply } from "../shared/outreach.ts";

const COLLECTIONS = ["campaigns", "accounts", "contacts", "signals", "touches", "replies", "meetings"] as const;

/**
 * The outreach dataset bound to the server from outside (DATA_PATH).
 *
 * It is read once at start and kept in memory; every mutation is applied in
 * memory first and then written back, so the file always reflects what the
 * app last showed.
 */
export class OutreachStore {
  #writes: Promise<unknown> = Promise.resolve();

  private constructor(
    readonly filePath: string,
    readonly data: OutreachData,
  ) {}

  static async open(filePath: string): Promise<OutreachStore> {
    const absolute = path.resolve(filePath);
    const raw = JSON.parse(await fs.readFile(absolute, "utf-8")) as Partial<OutreachData>;
    if (raw.version !== 1) {
      throw new Error(`${absolute}: unsupported dataset version ${String(raw.version)}; expected 1`);
    }
    for (const key of COLLECTIONS) {
      if (!Array.isArray(raw[key])) {
        throw new Error(`${absolute}: dataset has no "${key}" array`);
      }
    }
    if (typeof raw.asOf !== "string" || Number.isNaN(Date.parse(raw.asOf))) {
      throw new Error(`${absolute}: dataset has no valid "asOf" timestamp`);
    }
    return new OutreachStore(absolute, raw as OutreachData);
  }

  enroll(contactId: string, campaignId: string): Contact {
    const contact = this.data.contacts.find((c) => c.id === contactId);
    if (!contact) throw new Error(`No contact with id ${contactId}`);
    if (!this.data.campaigns.some((c) => c.id === campaignId)) {
      throw new Error(`No campaign with id ${campaignId}`);
    }
    if (contact.enrollment) {
      throw new Error(`${contact.firstName} ${contact.lastName} is already in a sequence`);
    }
    // Credit the newest signal on this person that led to the campaign, if any.
    const signal = this.data.signals
      .filter((s) => s.contactId === contactId && s.campaignId === campaignId)
      .at(-1);
    contact.enrollment = {
      campaignId,
      signalId: signal?.id ?? null,
      enrolledAt: new Date().toISOString(),
    };
    return contact;
  }

  markHandled(replyId: string): Reply {
    const reply = this.data.replies.find((r) => r.id === replyId);
    if (!reply) throw new Error(`No reply with id ${replyId}`);
    if (!reply.handled) {
      reply.handled = true;
      reply.handledAt = new Date().toISOString();
    }
    return reply;
  }

  /** Writes are serialized; each one saves the whole in-memory state atomically. */
  persist(): Promise<void> {
    const write = this.#writes.then(async () => {
      const temp = `${this.filePath}.${process.pid}.tmp`;
      await fs.writeFile(temp, `${JSON.stringify(this.data, null, 2)}\n`, "utf-8");
      await fs.rename(temp, this.filePath);
    });
    this.#writes = write.catch(() => undefined);
    return write;
  }
}
