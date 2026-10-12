import { PersonAvatar } from "@kit/components/person-avatar";
import {
  FilterRow,
  LayoutTabs,
  RefreshButton,
  SearchField,
  ViewHeader,
  type LayoutMode,
} from "@kit/components/view-header";
import {
  Select,
  SelectContent,
  SelectGroup,
  SelectItem,
  SelectLabel,
  SelectSeparator,
  SelectTrigger,
  SelectValue,
} from "@kit/ui/select";
import type { BoardSnapshot } from "@shared/schema";
import { SquareKanban } from "lucide-react";

export const ALL_PROJECTS = "all";
export const ANYONE = "anyone";
export const UNASSIGNED = "unassigned";
export type BoardMode = LayoutMode;

export function BoardToolbar({
  snapshot,
  shown,
  project,
  onProjectChange,
  assignee,
  onAssigneeChange,
  text,
  onTextChange,
  mode,
  onModeChange,
  loading,
  onRefresh,
}: {
  snapshot: BoardSnapshot | null;
  shown: number;
  project: string;
  onProjectChange: (project: string) => void;
  assignee: string;
  onAssigneeChange: (assignee: string) => void;
  text: string;
  onTextChange: (text: string) => void;
  mode: BoardMode;
  onModeChange: (mode: BoardMode) => void;
  loading: boolean;
  onRefresh: () => void;
}) {
  const scope = snapshot?.projects.find((p) => p.key === snapshot.project);
  const people = snapshot?.people ?? [];
  const overdue = snapshot?.tasks.filter((t) => t.overdue).length ?? 0;

  return (
    <header className="flex flex-col gap-3">
      <ViewHeader
        icon={SquareKanban}
        title={snapshot ? (scope ? scope.name : "All issues") : "Issues"}
        subtitle={
          snapshot ? (
            <>
              {shown === snapshot.tasks.length ? `${shown} issues` : `${shown} of ${snapshot.tasks.length} issues`}
              {overdue > 0 && <span className="text-danger"> · {overdue} overdue</span>}
            </>
          ) : (
            "Connecting to the tasks server…"
          )
        }
        actions={
          <>
            <LayoutTabs value={mode} onChange={onModeChange} />
            <RefreshButton busy={loading} onClick={onRefresh} />
          </>
        }
      />

      <FilterRow>
        <Select value={project} onValueChange={onProjectChange}>
          <SelectTrigger size="sm" className="min-w-[150px] flex-1 sm:flex-none" aria-label="Project">
            <SelectValue />
          </SelectTrigger>
          <SelectContent>
            <SelectItem value={ALL_PROJECTS}>All projects</SelectItem>
            <SelectSeparator />
            {(snapshot?.projects ?? []).map((p) => (
              <SelectItem key={p.key} value={p.key}>
                <span className="text-muted-foreground font-mono text-xs">{p.key}</span>
                {p.name}
              </SelectItem>
            ))}
          </SelectContent>
        </Select>

        <Select value={assignee} onValueChange={onAssigneeChange}>
          <SelectTrigger size="sm" className="min-w-[150px] flex-1 sm:flex-none" aria-label="Assignee">
            <SelectValue />
          </SelectTrigger>
          <SelectContent>
            <SelectItem value={ANYONE}>Anyone</SelectItem>
            <SelectItem value={UNASSIGNED}>
              <PersonAvatar person={null} className="size-4" />
              Unassigned
            </SelectItem>
            {(["human", "agent"] as const).map((kind) => (
              <SelectGroup key={kind}>
                <SelectSeparator />
                <SelectLabel>{kind === "human" ? "People" : "Agents"}</SelectLabel>
                {people
                  .filter((p) => p.kind === kind)
                  .map((p) => (
                    <SelectItem key={p.id} value={p.id}>
                      <PersonAvatar person={p} className="size-4" />
                      {p.name}
                      {p.id === snapshot?.viewer.id && <span className="text-subtle-foreground text-xs">you</span>}
                    </SelectItem>
                  ))}
              </SelectGroup>
            ))}
          </SelectContent>
        </Select>

        <SearchField
          value={text}
          onChange={onTextChange}
          placeholder="Filter by key, title, label or person"
          label="Filter issues"
        />
      </FilterRow>
    </header>
  );
}
