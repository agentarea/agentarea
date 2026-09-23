// @vitest-environment jsdom

import { act, renderHook } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import { useFileUpload } from "./useFileUpload";

function selectionEvent(file: File, input: HTMLInputElement) {
  Object.defineProperty(input, "files", {
    configurable: true,
    value: [file],
  });
  input.value = "C:\\fakepath\\report.txt";
  return {
    currentTarget: input,
    target: input,
  } as unknown as React.ChangeEvent<HTMLInputElement>;
}

describe("useFileUpload", () => {
  it("keeps selected files removable and allows selecting the same file again", () => {
    const { result } = renderHook(() => useFileUpload());
    const input = document.createElement("input");
    const file = new File(["report"], "report.txt", { type: "text/plain" });

    act(() => result.current.handleFileSelect(selectionEvent(file, input)));
    expect(result.current.selectedFiles).toEqual([file]);
    expect(input.value).toBe("");

    act(() => result.current.removeFile(0));
    expect(result.current.selectedFiles).toEqual([]);

    act(() => result.current.handleFileSelect(selectionEvent(file, input)));
    expect(result.current.selectedFiles).toEqual([file]);
  });
});
