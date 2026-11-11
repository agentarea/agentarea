import type { Senders } from "@/api/client/types.gen";

export type SendersChoice = Senders["allow"];

/** What the "who may write" control holds: the choice and the ids as typed. */
export interface SendersFormValue {
  allow: SendersChoice;
  ids: string;
}

/** A new bot answers only whoever adds it. */
export const DEFAULT_SENDERS: SendersFormValue = { allow: "owner", ids: "" };

/** The ids in `text`, split on commas, spaces and new lines, each once. */
export function parseSenderIds(text: string): string[] {
  return [...new Set(text.split(/[\s,;]+/).filter(Boolean))];
}

/** Ids that are not numeric account ids. */
export function invalidSenderIds(text: string): string[] {
  return parseSenderIds(text).filter((id) => !/^\d+$/.test(id));
}

/** Whether `value` can be saved: a list needs at least one id, every one numeric. */
export function sendersReady(value: SendersFormValue): boolean {
  if (value.allow !== "ids") return true;
  return (
    parseSenderIds(value.ids).length > 0 &&
    invalidSenderIds(value.ids).length === 0
  );
}

export function toSenders(value: SendersFormValue): Senders {
  return value.allow === "ids"
    ? { allow: "ids", ids: parseSenderIds(value.ids) }
    : { allow: value.allow };
}

/** The control's value for a source; one added before the choice existed admits members. */
export function fromSenders(
  senders: Senders | null | undefined
): SendersFormValue {
  if (!senders) return { allow: "members", ids: "" };
  return { allow: senders.allow, ids: (senders.ids ?? []).join(", ") };
}
