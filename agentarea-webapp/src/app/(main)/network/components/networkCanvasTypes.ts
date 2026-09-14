import type { CSSProperties } from "react";
import type { NetworkPersonAgentAccess } from "@/api/client/types.gen";

export interface CanvasPoint {
  x: number;
  y: number;
}
export interface CanvasNode<
  Data extends Record<string, unknown> = Record<string, unknown>,
> {
  id: string;
  type: "networkAgent" | "organization" | "people" | "region";
  position: CanvasPoint;
  width: number;
  height: number;
  data: Data;
  ariaLabel?: string;
  focusable?: boolean;
  zIndex?: number;
}
export interface CanvasEdge {
  id: string;
  source: string;
  target: string;
  data: {
    relation: string;
    decision?: NetworkPersonAgentAccess;
    points?: CanvasPoint[];
    labelPosition?: CanvasPoint;
  };
  style: Pick<
    CSSProperties,
    "stroke" | "strokeWidth" | "opacity" | "strokeDasharray"
  >;
  label?: string;
  ariaLabel?: string;
  selected?: boolean;
  zIndex?: number;
}
export interface CanvasControls {
  zoomBy: (factor: number) => void;
  fit: () => void;
}
