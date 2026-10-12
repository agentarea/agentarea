import type { BoardSnapshot, TaskRow } from "@shared/schema";
import type { LabelColor, Status } from "@shared/tasks";

/** What the board and the list views share: the rows on screen and what can be done to them. */
export type BoardViewProps = {
  snapshot: BoardSnapshot;
  tasks: TaskRow[];
  labelColors: Map<string, LabelColor>;
  saving: Record<string, boolean>;
  notes: Record<string, string>;
  composing: Status | null;
  onCompose: (status: Status | null) => void;
  onOpen: (task: TaskRow) => void;
  onMove: (task: TaskRow, status: Status) => void;
  onCreate: (input: { title: string; project: string; status: Status }) => Promise<string | null>;
};
