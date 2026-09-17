"use client";

import { useMemo, useRef, useState, type DragEvent } from "react";
import {
  createDragTracker,
  dispatchDrop,
  DRAG_PATH_TYPE,
  dragKind,
  type DropHandlers,
} from "@/lib/file-drop";

export interface FileDropOptions extends DropHandlers {
  disabled?: boolean;
}

/** Wire a drop surface that accepts OS files, in-app items, or both.
 *
 * Which of the two a zone accepts follows from the handlers it passes: a zone
 * with only `onFiles` stays inert under an in-app drag rather than lighting up
 * and then swallowing the drop.
 *
 * `dropProps` spreads onto any element, so a surface made of many small zones
 * (a folder row, a tree node) costs no extra markup. Events stop at the zone
 * that handles them, letting an inner zone win over the one wrapping it.
 */
export function useFileDrop({ onFiles, onMove, disabled }: FileDropOptions) {
  const [isDragging, setIsDragging] = useState(false);
  const tracker = useRef(createDragTracker()).current;

  const dropProps = useMemo(() => {
    const accepts = (dataTransfer: DataTransfer) => {
      if (disabled) return false;
      const kind = dragKind(dataTransfer);
      return (kind === "files" && Boolean(onFiles)) || (kind === "path" && Boolean(onMove));
    };

    return {
      onDragEnter: (event: DragEvent) => {
        if (!accepts(event.dataTransfer)) return;
        event.preventDefault();
        event.stopPropagation();
        if (tracker.enter()) setIsDragging(true);
      },
      onDragOver: (event: DragEvent) => {
        if (!accepts(event.dataTransfer)) return;
        // Without preventDefault on every dragover the browser never fires drop.
        event.preventDefault();
        event.stopPropagation();
        event.dataTransfer.dropEffect =
          dragKind(event.dataTransfer) === "files" ? "copy" : "move";
      },
      onDragLeave: (event: DragEvent) => {
        if (!accepts(event.dataTransfer)) return;
        event.stopPropagation();
        if (tracker.leave()) setIsDragging(false);
      },
      onDrop: (event: DragEvent) => {
        if (!accepts(event.dataTransfer)) return;
        event.preventDefault();
        event.stopPropagation();
        tracker.reset();
        setIsDragging(false);
        dispatchDrop(event.dataTransfer, { onFiles, onMove });
      },
    };
  }, [disabled, onFiles, onMove, tracker]);

  return { isDragging, dropProps };
}

/** Build the `dragstart` payload that makes an element a move source. */
export function dragSourceProps(path: string) {
  return {
    draggable: true,
    onDragStart: (event: DragEvent) => {
      event.stopPropagation();
      event.dataTransfer.effectAllowed = "move";
      event.dataTransfer.setData(DRAG_PATH_TYPE, path);
      // Dragging out of the app then reads as the path rather than as nothing.
      event.dataTransfer.setData("text/plain", path);
    },
  };
}
