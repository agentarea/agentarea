"use client";

import { createContext, useContext } from "react";
import type { TileFrame } from "../utils/canvasState";
import type {
  CanvasAgent,
  CanvasApp,
  CanvasConnection,
  CanvasTask,
  CanvasTrigger,
} from "./canvasTypes";
import type { CanvasLive } from "./useCanvasLive";

export type CanvasTileActions = {
  apps: ReadonlyMap<string, CanvasApp>;
  agents: ReadonlyMap<string, CanvasAgent>;
  connections: ReadonlyMap<string, CanvasConnection>;
  triggers: CanvasTrigger[];
  tasks: CanvasTask[];
  tasksById: ReadonlyMap<string, CanvasTask>;
  removeTile: (tileId: string) => void;
  setNote: (tileId: string, text: string) => void;
  setLinkLabel: (linkId: string, label: string) => void;
  removeLink: (linkId: string) => void;
  live: CanvasLive;
  /** Put the task on the canvas next to the tile it was opened from. */
  openTask: (task: CanvasTask, from: TileFrame) => void;
};

export const CanvasTileContext = createContext<CanvasTileActions | null>(null);

export function useCanvasTiles(): CanvasTileActions {
  const value = useContext(CanvasTileContext);
  if (!value) throw new Error("Canvas tiles render inside CanvasTileContext");
  return value;
}
