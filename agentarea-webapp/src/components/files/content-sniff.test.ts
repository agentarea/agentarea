import { describe, expect, it } from "vitest";
import { looksTextual, mediaKind, sniffMedia } from "./content-sniff";

const bytes = (...values: number[]) => new Uint8Array(values);
const utf8 = (text: string) => new TextEncoder().encode(text);

describe("looksTextual", () => {
  it("accepts plain text", () => {
    expect(looksTextual(utf8("# Heading\n\nsome prose\n"))).toBe(true);
  });

  it("accepts multi-byte characters", () => {
    expect(looksTextual(utf8("привет — ok ✅"))).toBe(true);
  });

  it("accepts an empty file", () => {
    expect(looksTextual(bytes())).toBe(true);
  });

  it("rejects a PNG header", () => {
    expect(looksTextual(bytes(0x89, 0x50, 0x4e, 0x47, 0x0d, 0x0a, 0x1a, 0x0a))).toBe(
      false
    );
  });

  it("rejects text carrying a NUL, which no editor writes", () => {
    expect(looksTextual(bytes(0x68, 0x69, 0x00, 0x68, 0x69))).toBe(false);
  });

  it("rejects bytes that are not valid UTF-8", () => {
    expect(looksTextual(bytes(0xc3, 0x28))).toBe(false);
  });

  it("accepts a chunk that ends mid-character", () => {
    // Reading a fixed-size chunk splits multi-byte characters; a truncated
    // tail is not evidence of binary content.
    const full = utf8("двадцать восемь символов ровно");
    expect(looksTextual(full.slice(0, full.length - 1))).toBe(true);
  });
});

describe("mediaKind", () => {
  it("reads the standard families", () => {
    expect(mediaKind("image/png")).toBe("image");
    expect(mediaKind("video/mp4")).toBe("video");
    expect(mediaKind("audio/mpeg")).toBe("audio");
    expect(mediaKind("application/pdf")).toBe("pdf");
  });

  it("ignores parameters the server appends", () => {
    expect(mediaKind("image/svg+xml; charset=utf-8")).toBe("image");
  });

  it("has no opinion on anything else", () => {
    expect(mediaKind("application/octet-stream")).toBe(null);
    expect(mediaKind("text/plain")).toBe(null);
    expect(mediaKind(null)).toBe(null);
    expect(mediaKind(undefined)).toBe(null);
  });
});

describe("sniffMedia", () => {
  it("does not take text for a video because mimetypes calls .ts one", async () => {
    const response = new Response("export const a = 1;\n");
    expect(await sniffMedia(response, "video/mp2t")).toBe(null);
  });

  it("takes binary bytes as the declared family", async () => {
    const response = new Response(bytes(0x00, 0x00, 0x00, 0x18, 0x66, 0x74, 0x79, 0x70));
    expect(await sniffMedia(response, "video/mp4")).toBe("video");
  });
});
