import React from "react";
import type { Part } from "../contract";
import { FileChip } from "@/components/Chat/utils/fileIcon";

function asString(value: unknown): string | undefined {
  return typeof value === "string" && value ? value : undefined;
}

/** Placeholder artifact card: name/path plus a file chip when a path is known. */
export const ArtifactPart: React.FC<{ part: Part }> = ({ part }) => {
  const name =
    asString(part.data.name) ??
    asString(part.data.path) ??
    asString(part.data.filename) ??
    `Artifact ${part.partId}`;
  const path = asString(part.data.path) ?? asString(part.data.filename);

  return (
    <div className="rounded-md border border-border bg-muted/30 px-3 py-2">
      {path ? (
        <FileChip name={path} />
      ) : (
        <span className="text-sm text-foreground">{name}</span>
      )}
    </div>
  );
};

export default ArtifactPart;
