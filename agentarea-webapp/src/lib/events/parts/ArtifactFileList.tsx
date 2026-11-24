"use client";

import type { ReactNode } from "react";
import { fileBasename } from "@/components/Chat/utils/fileIcon";
import { cn } from "@/lib/utils";
import { ArtifactMedia } from "./ArtifactMedia";

export interface ArtifactFile {
  path: string;
  href?: string;
  mimeType?: string | null;
}

/** Files a step produced under a one-line caption: pictures shown, the rest as chips. */
export function ArtifactFileList({
  label,
  files,
  className,
}: {
  label: ReactNode;
  files: ArtifactFile[];
  className?: string;
}) {
  return (
    <div className={cn("flex flex-col gap-1", className)}>
      <span className="text-[11px] text-muted-foreground">{label}</span>
      <div className="flex flex-wrap gap-2">
        {files.map((file) => (
          <ArtifactMedia
            key={file.path}
            path={file.path}
            name={fileBasename(file.path)}
            href={file.href}
            mimeType={file.mimeType}
          />
        ))}
      </div>
    </div>
  );
}
