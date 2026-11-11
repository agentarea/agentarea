import type { SourceCreate, StreamCreate } from "@/api/client/types.gen";
import type { SourceType } from "@/lib/sourceTypes";
import {
  sendersReady,
  toSenders,
  type SendersFormValue,
} from "../../events/[streamId]/senders";
import { sourceKinds } from "../../events/[streamId]/sourceRequest";

/** What the new-channel form holds: typed credential values, not secret picks. */
export interface ChannelFormValues {
  sourceType: string;
  name: string;
  credentials: Record<string, string>;
  settings: Record<string, string>;
  senders: SendersFormValue;
  agentId: string;
}

/** Everything one channel is made of: a stream, the source feeding it, the trigger on it. */
export interface ChannelRequest {
  name: string;
  stream: StreamCreate;
  source: SourceCreate;
  agentId: string;
}

/** A catalog entry a channel can be made of: a conversation the agent answers in. */
export function isChannelType(type: SourceType): boolean {
  return type.replies && type.continues_sessions;
}

/** The credentials a member types in; one the platform issues is left to it. */
export function typedCredentials(type: SourceType) {
  return type.credentials.filter((field) => !field.issued);
}

export function toChannelRequest(
  type: SourceType,
  values: ChannelFormValues
): ChannelRequest {
  const name = values.name.trim() || type.name;
  const credentials: Record<string, string> = {};
  for (const field of typedCredentials(type)) {
    const value = values.credentials[field.key]?.trim();
    if (value) credentials[field.key] = value;
  }
  const config: Record<string, string> = {};
  for (const field of type.config) {
    const value = values.settings[field.key]?.trim();
    if (value) config[field.key] = value;
  }
  const source: SourceCreate = {
    source_type: type.slug,
    kind: sourceKinds(type)[0],
    credentials,
    config,
  };
  if (type.admits_senders) source.senders = toSenders(values.senders);
  return {
    name,
    stream: { name, description: "" },
    source,
    agentId: values.agentId,
  };
}

/** Keys of what the form still needs before the channel can be made. */
export function missingChannelFields(
  type: SourceType,
  values: ChannelFormValues
): string[] {
  const blank = (value: string | undefined) => !value?.trim();
  return [
    ...typedCredentials(type)
      .filter((f) => f.required && blank(values.credentials[f.key]))
      .map((f) => f.key),
    ...type.config
      .filter((f) => f.required && !f.issued && blank(values.settings[f.key]))
      .map((f) => f.key),
    ...(type.admits_senders && !sendersReady(values.senders)
      ? ["senders"]
      : []),
    ...(blank(values.agentId) ? ["agent"] : []),
  ];
}
