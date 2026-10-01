import React from "react";
import type { Part } from "../contract";
import { ArtifactMedia } from "./ArtifactMedia";

function asString(value: unknown): string | undefined {
  return typeof value === "string" && value ? value : undefined;
}

function asReachableHref(value: unknown): string | undefined {
  const href = asString(value);
  return href && /^(https?:\/\/|\/)/i.test(href) ? href : undefined;
}

/** Artifact row with a truthful file identity and optional real link; an
 * image or a video is shown inline. */
export const ArtifactPart: React.FC<{ part: Part }> = ({ part }) => {
  const name =
    asString(part.data.name) ??
    asString(part.data.path) ??
    asString(part.data.filename) ??
    `Artifact ${part.partId}`;
  const path = asString(part.data.path) ?? asString(part.data.filename);
  const href =
    asReachableHref(part.data.download_url) ??
    asReachableHref(part.data.href) ??
    asReachableHref(part.data.url);
  const mimeType =
    asString(part.data.mime_type) ?? asString(part.data.content_type);

  return (
    <ArtifactMedia
      path={path}
      name={name}
      href={href}
      mimeType={mimeType}
      className="px-1 py-0.5 text-[13px] leading-5"
    />
  );
};

export default ArtifactPart;
