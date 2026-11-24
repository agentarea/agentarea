import { describe, expect, it } from "vitest";
import type { SourceType } from "@/lib/sourceTypes";
import {
  isChannelType,
  missingChannelFields,
  toChannelRequest,
  type ChannelFormValues,
} from "./channelRequest";

const field = (key: string, required: boolean, issued = false) => ({
  key,
  label: key,
  placeholder: "",
  required,
  issued,
  format: "token" as const,
});

const bot: SourceType = {
  slug: "bot",
  name: "Bot",
  description: "",
  icon: "bot",
  icon_url: null,
  delivery: "both",
  credentials: [field("bot_token", true), field("secret_token", false, true)],
  config: [],
  events: [],
  event: {
    kind: "message",
    key: null,
    session_key: null,
    sender: null,
    occurred_at: null,
  },
  verification_scheme: null,
  verification_header: null,
  continues_sessions: true,
  admits_senders: true,
  replies: true,
  registers_webhook: true,
};

const values = (over: Partial<ChannelFormValues> = {}): ChannelFormValues => ({
  sourceType: "bot",
  name: "",
  credentials: {},
  settings: {},
  senders: { allow: "owner", ids: "" },
  agentId: "",
  ...over,
});

describe("channelRequest", () => {
  it("makes a channel only of a type the agent answers in", () => {
    expect(isChannelType(bot)).toBe(true);
    expect(isChannelType({ ...bot, replies: false })).toBe(false);
    expect(isChannelType({ ...bot, continues_sessions: false })).toBe(false);
  });

  it("asks for the typed token and the agent, not for what is issued", () => {
    expect(missingChannelFields(bot, values())).toEqual(["bot_token", "agent"]);
    expect(
      missingChannelFields(
        bot,
        values({ credentials: { bot_token: "1:x" }, agentId: "a" })
      )
    ).toEqual([]);
  });

  it("names the stream and trigger after the type when left blank", () => {
    const request = toChannelRequest(
      bot,
      values({ credentials: { bot_token: " 1:x " }, agentId: "a" })
    );
    expect(request.name).toBe("Bot");
    expect(request.stream).toEqual({ name: "Bot", description: "" });
    expect(request.source).toEqual({
      source_type: "bot",
      kind: "webhook",
      credentials: { bot_token: "1:x" },
      config: {},
      senders: { allow: "owner" },
    });
  });

  it("passes the listed ids for a bot that answers only them", () => {
    const request = toChannelRequest(
      bot,
      values({
        name: "Mine",
        credentials: { bot_token: "1:x" },
        senders: { allow: "ids", ids: "111, 222" },
        agentId: "a",
      })
    );
    expect(request.name).toBe("Mine");
    expect(request.source.senders).toEqual({
      allow: "ids",
      ids: ["111", "222"],
    });
  });
});
