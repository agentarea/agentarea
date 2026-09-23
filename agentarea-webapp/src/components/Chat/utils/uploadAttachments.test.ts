import { afterEach, describe, expect, it, vi } from "vitest";
import { uploadAttachment } from "./uploadAttachments";

describe("uploadAttachment", () => {
  afterEach(() => vi.unstubAllGlobals());

  it("presigns with file integrity metadata and uploads the same file", async () => {
    const file = new File(["abc"], "report.txt", { type: "text/plain" });
    const fetchMock = vi
      .fn()
      .mockResolvedValueOnce(
        new Response(
          JSON.stringify({
            ref: "staging/ref-1",
            upload_url: "https://uploads.test/ref-1",
          }),
          { status: 200 }
        )
      )
      .mockResolvedValueOnce(new Response(null, { status: 200 }));
    vi.stubGlobal("fetch", fetchMock);

    await expect(uploadAttachment(file)).resolves.toBe("staging/ref-1");

    const [, presignInit] = fetchMock.mock.calls[0];
    expect(JSON.parse(String(presignInit?.body))).toEqual({
      content_type: "text/plain",
      filename: "report.txt",
      sha256:
        "ba7816bf8f01cfea414140de5dae2223b00361a396177a9cb410ff61f20015ad", // pragma: allowlist secret
      size: 3,
    });
    expect(fetchMock.mock.calls[1][0]).toBe("https://uploads.test/ref-1");
    expect(fetchMock.mock.calls[1][1]).toMatchObject({
      body: file,
      method: "PUT",
    });
  });

  it("rejects when object-store upload fails", async () => {
    const file = new File(["abc"], "report.txt", { type: "text/plain" });
    vi.stubGlobal(
      "fetch",
      vi
        .fn()
        .mockResolvedValueOnce(
          new Response(
            JSON.stringify({
              ref: "staging/ref-1",
              upload_url: "https://uploads.test/ref-1",
            }),
            { status: 200 }
          )
        )
        .mockResolvedValueOnce(
          new Response("upload unavailable", { status: 503 })
        )
    );

    await expect(uploadAttachment(file)).rejects.toThrow("upload unavailable");
  });
});
