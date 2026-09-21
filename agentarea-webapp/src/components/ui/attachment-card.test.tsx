import { renderToStaticMarkup } from "react-dom/server";
import { describe, expect, it } from "vitest";
import { AttachmentCard } from "./attachment-card";

describe("AttachmentCard", () => {
  it.each([
    ["remove", "Remove report.txt"],
    ["download", "Download report.txt"],
  ] as const)("names the %s action", (actionType, label) => {
    const markup = renderToStaticMarkup(
      <AttachmentCard
        actionType={actionType}
        file={new File(["report"], "report.txt", { type: "text/plain" })}
        onAction={() => undefined}
      />
    );

    expect(markup).toContain(`aria-label="${label}"`);
  });
});
