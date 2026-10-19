import { describe, expect, it } from "vitest";
import {
  defaultSession,
  resolveSession,
  sourceTypeBySlug,
  streamContinuesSessions,
  type SourceType,
} from "./sourceTypes";

function entry(slug: string, sessionKey: string | null): SourceType {
  return {
    slug,
    name: slug,
    description: "",
    icon: "webhook",
    icon_url: null,
    delivery: "webhook",
    credentials: [],
    config: [],
    events: [],
    event: {
      kind: "{body:type}",
      key: null,
      session_key: sessionKey,
      sender: null,
      occurred_at: null,
    },
    verification_scheme: null,
    verification_header: null,
    continues_sessions: sessionKey !== null,
    replies: false,
  };
}

const chat = entry("chat_bot", "{body:message.chat.id}");
const hook = entry("repo_host", null);
const types = [chat, hook];

describe("sourceTypeBySlug", () => {
  it("finds the entry by slug and nothing for a missing one", () => {
    expect(sourceTypeBySlug(types, "repo_host")).toBe(hook);
    expect(sourceTypeBySlug(types, "gone")).toBeUndefined();
    expect(sourceTypeBySlug(types, null)).toBeUndefined();
  });
});

describe("streamContinuesSessions", () => {
  it("is on when any source of the stream names a session", () => {
    expect(streamContinuesSessions(types, ["repo_host", "chat_bot"])).toBe(
      true
    );
  });

  it("is off for sources without sessions, unknown slugs and no sources", () => {
    expect(streamContinuesSessions(types, ["repo_host"])).toBe(false);
    expect(streamContinuesSessions(types, ["gone", null])).toBe(false);
    expect(streamContinuesSessions(types, [])).toBe(false);
  });
});

describe("defaultSession", () => {
  it("continues with the default wait when the stream has sessions", () => {
    expect(defaultSession(true)).toEqual({
      continue: true,
      idle_timeout: "30m",
    });
    expect(defaultSession(false).continue).toBe(false);
  });
});

describe("resolveSession", () => {
  it("fills each null with the stream's default and keeps what was set", () => {
    expect(resolveSession(null, true)).toEqual(defaultSession(true));
    expect(
      resolveSession({ continue: null, idle_timeout: "1h" }, false)
    ).toEqual({ continue: false, idle_timeout: "1h" });
    expect(
      resolveSession({ continue: false, idle_timeout: null }, true)
    ).toEqual({ continue: false, idle_timeout: "30m" });
  });
});
