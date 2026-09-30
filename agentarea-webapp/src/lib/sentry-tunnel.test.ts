import { describe, expect, it } from "vitest";
import { envelopeUpstream, readCapped } from "./sentry-tunnel";

const SAAS_DSN =
  "https://0123abcd@o4500000000000001.ingest.de.sentry.io/4500000000000002";
const SELF_HOSTED_DSN = "https://0123abcd@errors.example.com/glitchtip/7";

const header = (dsn: unknown) =>
  JSON.stringify({ event_id: "e1", sent_at: "2026-10-01T00:00:00Z", dsn });

describe("envelopeUpstream", () => {
  it("forwards an envelope for the configured SaaS DSN to its ingest endpoint", () => {
    expect(envelopeUpstream(header(SAAS_DSN), SAAS_DSN)).toBe(
      "https://o4500000000000001.ingest.de.sentry.io/api/4500000000000002/envelope/?sentry_version=7&sentry_key=0123abcd"
    );
  });

  it("keeps the path prefix of a self-hosted DSN", () => {
    expect(envelopeUpstream(header(SELF_HOSTED_DSN), SELF_HOSTED_DSN)).toBe(
      "https://errors.example.com/glitchtip/api/7/envelope/?sentry_version=7&sentry_key=0123abcd"
    );
  });

  it("refuses an envelope addressed to another project", () => {
    const foreign =
      "https://0123abcd@o4500000000000001.ingest.de.sentry.io/999";
    expect(envelopeUpstream(header(foreign), SAAS_DSN)).toBeNull();
  });

  it("refuses an envelope addressed to another host", () => {
    const foreign = "https://0123abcd@attacker.example.com/4500000000000002";
    expect(envelopeUpstream(header(foreign), SAAS_DSN)).toBeNull();
  });

  it("refuses an envelope signed with another key", () => {
    const foreign =
      "https://ffff@o4500000000000001.ingest.de.sentry.io/4500000000000002";
    expect(envelopeUpstream(header(foreign), SAAS_DSN)).toBeNull();
  });

  it("refuses everything when no DSN is configured", () => {
    expect(envelopeUpstream(header(SAAS_DSN), undefined)).toBeNull();
    expect(envelopeUpstream(header(SAAS_DSN), "")).toBeNull();
  });

  it("refuses a header without a DSN", () => {
    expect(envelopeUpstream(header(undefined), SAAS_DSN)).toBeNull();
  });

  it("refuses a header that is not JSON", () => {
    expect(envelopeUpstream("not json", SAAS_DSN)).toBeNull();
  });
});

describe("readCapped", () => {
  const streamOf = (...chunks: string[]) =>
    new ReadableStream<Uint8Array>({
      start(controller) {
        for (const chunk of chunks)
          controller.enqueue(new TextEncoder().encode(chunk));
        controller.close();
      },
    });

  it("returns the whole body when it fits", async () => {
    const body = await readCapped(streamOf("ab", "cd"), 4);
    expect(body && new TextDecoder().decode(body)).toBe("abcd");
  });

  it("gives up as soon as the body exceeds the cap", async () => {
    expect(await readCapped(streamOf("ab", "cd", "e"), 4)).toBeNull();
  });

  it("returns an empty body for a missing stream", async () => {
    expect(await readCapped(null, 4)).toEqual(new Uint8Array(0));
  });
});
