import type { TaskDetail } from "@shared/schema";
import { LinkList, LinkRow } from "@kit/components/list";
import { FieldNote } from "@kit/components/notes";
import { PersonAvatar } from "@kit/components/person-avatar";
import { DetailLayout } from "@kit/components/properties";
import { Section } from "@kit/components/section";
import { DetailSkeleton } from "@kit/components/skeletons";
import { Breadcrumb, RefreshButton } from "@kit/components/view-header";
import { ChevronRight, GitFork, SquareKanban } from "lucide-react";
import { useState } from "react";
import { PriorityIcon } from "@/components/priority-icon";
import { StatusIcon } from "@/components/status-icon";
import { Input } from "@kit/ui/input";
import { Markdown } from "@/lib/markdown";
import { cn } from "@kit/lib/utils";
import { IssueProperties } from "./issue-properties";
import { IssueTimeline } from "./issue-timeline";
import type { FieldState, IssueActions } from "./types";

function Title({ card, state, onUpdate }: { card: TaskDetail; state: FieldState; onUpdate: IssueActions["onUpdate"] }) {
  const [draft, setDraft] = useState<string | null>(null);
  const save = () => {
    const title = draft?.trim();
    setDraft(null);
    if (title && title !== card.title) onUpdate("title", { title }, (c) => ({ ...c, title }));
  };
  return (
    <div className="flex flex-col gap-1">
      {draft === null ? (
        <h1
          className="hover:bg-muted/60 -mx-1.5 cursor-text rounded-md px-1.5 py-0.5 text-xl leading-snug font-semibold tracking-tight"
          title="Click to rename"
          onClick={() => setDraft(card.title)}
        >
          {card.title}
        </h1>
      ) : (
        <Input
          autoFocus
          value={draft}
          aria-label="Title"
          className="h-9 text-lg font-semibold"
          onChange={(event) => setDraft(event.target.value)}
          onBlur={save}
          onKeyDown={(event) => {
            if (event.key === "Enter") save();
            if (event.key === "Escape") setDraft(null);
          }}
        />
      )}
      <FieldNote busy={state.busy.title} note={state.notes.title} />
    </div>
  );
}

function SubIssues({ card, onOpenIssue }: { card: TaskDetail; onOpenIssue: IssueActions["onOpenIssue"] }) {
  if (!card.children.length) return null;
  return (
    <Section title="Sub-issues" meta={`${card.subIssues.done}/${card.subIssues.total} done`}>
      <LinkList>
        {card.children.map((child) => (
          <LinkRow key={child.id} onClick={() => onOpenIssue(child.key)}>
            <PriorityIcon priority={child.priority} />
            <span className="text-muted-foreground w-14 shrink-0 font-mono text-[11px]">{child.key}</span>
            <StatusIcon status={child.status} />
            <span
              className={cn(
                "min-w-0 flex-1 truncate",
                child.status === "canceled" && "text-muted-foreground line-through",
              )}
            >
              {child.title}
            </span>
            <PersonAvatar person={child.assignee} />
          </LinkRow>
        ))}
      </LinkList>
    </Section>
  );
}

export function IssueView({ card, state, actions }: { card: TaskDetail; state: FieldState; actions: IssueActions }) {
  return (
    <div className="flex flex-col gap-4">
      <header className="flex flex-col gap-1">
        <div className="flex items-center gap-2">
          <Breadcrumb>
            <button
              type="button"
              onClick={actions.onOpenBoard}
              className="hover:text-foreground inline-flex min-w-0 cursor-pointer items-center gap-1.5 truncate"
            >
              <SquareKanban className="size-3.5 shrink-0" />
              <span className="truncate">{card.projectName}</span>
            </button>
            {card.parent && (
              <>
                <ChevronRight className="size-3 shrink-0" />
                <button
                  type="button"
                  onClick={() => actions.onOpenIssue(card.parent!.key)}
                  className="hover:text-foreground inline-flex min-w-0 cursor-pointer items-center gap-1 truncate font-mono"
                  title={card.parent.title}
                >
                  <GitFork className="size-3 shrink-0" />
                  {card.parent.key}
                </button>
              </>
            )}
            <ChevronRight className="size-3 shrink-0" />
            <span className="text-foreground font-mono font-medium">{card.key}</span>
          </Breadcrumb>
          <RefreshButton compact className="ml-auto" busy={state.busy.refresh} onClick={actions.onRefresh} />
        </div>
        <FieldNote note={state.notes.link} />
      </header>

      <Title card={card} state={state} onUpdate={actions.onUpdate} />

      <DetailLayout
        main={
          <>
            {card.description ? (
              <Markdown text={card.description} />
            ) : (
              <p className="text-subtle-foreground text-sm">No description.</p>
            )}
            <SubIssues card={card} onOpenIssue={actions.onOpenIssue} />
            <IssueTimeline card={card} state={state} onComment={actions.onComment} />
          </>
        }
        aside={<IssueProperties card={card} state={state} onUpdate={actions.onUpdate} />}
      />
    </div>
  );
}

export function IssueSkeleton() {
  return <DetailSkeleton label="Loading issue" />;
}
