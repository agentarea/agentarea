"use client";

import { useState, type DragEvent, type HTMLAttributes } from "react";
import { dragSourceProps, useFileDrop } from "@/hooks/use-file-drop";
import {
  dispatchDrop,
  dragKind,
  type DropHandlers,
  type DroppedFile,
} from "@/lib/file-drop";
import { cn } from "@/lib/utils";
import { canMoveInto, isTaskOwned } from "./drop-rules";
import type { TreeNode } from "./file-tree";

/** Drag and drop for a folder view: OS files land in a folder, and items move
 * between folders.
 *
 * Both gestures share one surface — a row is a drag source and, if it is a
 * folder, a drop target — so the rules live together rather than being spelled
 * out again at each place a folder is drawn. */
export function useFolderDnd({
  folder,
  onUploadFiles,
  onMove,
}: {
  /** The folder on screen, which the pane-wide zone uploads into. */
  folder: string;
  onUploadFiles?: (files: DroppedFile[], destination: string) => void;
  onMove?: (source: string, destination: string) => void;
}) {
  // What the user is dragging, and which folder the cursor currently offers it
  // to. `hoveredFolder` is driven by dragover rather than dragenter/dragleave:
  // it fires continuously on whatever is under the cursor, so the highlight
  // cannot drift out of step with where the drop would actually land.
  const [draggingPath, setDraggingPath] = useState<string | null>(null);
  const [hoveredFolder, setHoveredFolder] = useState<string | null>(null);

  const pane = useFileDrop({
    onFiles: onUploadFiles
      ? (dropped) => onUploadFiles(dropped, folder)
      : undefined,
  });

  /** Make a folder — a row, a tree node, the root — a drop target. */
  const folderTarget = (folderPath: string) => {
    const writable = !isTaskOwned(folderPath);
    const handlers: DropHandlers = {
      onFiles:
        onUploadFiles && writable
          ? (dropped) => onUploadFiles(dropped, folderPath)
          : undefined,
      // With nothing dragged yet the target is merely potential, so it stays
      // enabled; the specific pairing is judged once a source is known.
      onMove:
        onMove && (!draggingPath || canMoveInto(draggingPath, folderPath))
          ? (source) => onMove(source, folderPath)
          : undefined,
    };
    const accepts = (dataTransfer: DataTransfer) => {
      const kind = dragKind(dataTransfer);
      return (
        (kind === "files" && Boolean(handlers.onFiles)) ||
        (kind === "path" && Boolean(handlers.onMove))
      );
    };
    return {
      onDragOver: (event: DragEvent) => {
        if (!accepts(event.dataTransfer)) return;
        // Claim the drop from the pane-wide zone this sits inside.
        event.preventDefault();
        event.stopPropagation();
        event.dataTransfer.dropEffect =
          dragKind(event.dataTransfer) === "files" ? "copy" : "move";
        setHoveredFolder(folderPath);
      },
      onDrop: (event: DragEvent) => {
        if (!accepts(event.dataTransfer)) return;
        event.preventDefault();
        event.stopPropagation();
        setHoveredFolder(null);
        setDraggingPath(null);
        dispatchDrop(event.dataTransfer, handlers);
      },
    };
  };

  const dragSource = (path: string) =>
    onMove && !isTaskOwned(path)
      ? {
          ...dragSourceProps(path),
          onDragStart: (event: DragEvent) => {
            dragSourceProps(path).onDragStart(event);
            setDraggingPath(path);
          },
          onDragEnd: () => {
            setDraggingPath(null);
            setHoveredFolder(null);
          },
        }
      : {};

  /** Everything one entry needs, whether it is drawn as a row or a tree node. */
  const entryProps = (entry: TreeNode): HTMLAttributes<HTMLElement> => ({
    ...dragSource(entry.path),
    ...(entry.isFile ? {} : folderTarget(entry.path)),
    className: cn(
      !entry.isFile &&
        hoveredFolder === entry.path &&
        "bg-primary/10 outline outline-2 outline-primary",
      draggingPath === entry.path && "opacity-50"
    ),
  });

  return {
    isDragging: pane.isDragging,
    /** Spread on the pane; its dragover must also clear `hoveredFolder`. */
    paneProps: pane.dropProps,
    hoveredFolder,
    clearHover: () => setHoveredFolder(null),
    folderTarget,
    entryProps,
  };
}
