import type { DealRow, PipelineSnapshot } from "@shared/schema";
import type { MoveTarget } from "@/lib/pipeline";

export type NewDeal = { title: string; value: number; stageId: string; ownerId: string };

/** What the board and the list share: the deals on screen and what can be done to them. */
export type PipelineViewProps = {
  snapshot: PipelineSnapshot;
  deals: DealRow[];
  saving: Record<string, boolean>;
  notes: Record<string, string>;
  composing: string | null;
  onCompose: (stageId: string | null) => void;
  onCreate: (deal: NewDeal) => Promise<string | null>;
  onOpen: (deal: DealRow) => void;
  onMove: (deal: DealRow, target: MoveTarget) => void;
  /** The deal waiting for a lost reason, if any. */
  losing: DealRow | null;
  lossBusy: boolean;
  lossError: string | null;
  onAskLost: (deal: DealRow) => void;
  onCancelLost: () => void;
};
