import type { TaskDetail } from "@shared/schema";
import { PRIORITIES, STATUSES } from "@shared/tasks";
import { X } from "lucide-react";
import { LabelChip } from "@kit/components/chip";
import { FieldNote } from "@kit/components/notes";
import { PersonAvatar, PersonName } from "@kit/components/person-avatar";
import { PropertyFooter, PropertyPanel, PropertyRow as Row, PropertyValue } from "@kit/components/properties";
import { PriorityIcon } from "@/components/priority-icon";
import { StatusIcon } from "@/components/status-icon";
import { Button } from "@kit/ui/button";
import { Input } from "@kit/ui/input";
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
import { formatDateTime, timeAgo } from "@/lib/format";
import { PRIORITY_META, STATUS_META } from "@/lib/meta";
import type { FieldState, IssueActions } from "./types";

const UNASSIGNED = "unassigned";

export function IssueProperties({
  card,
  state,
  onUpdate,
}: {
  card: TaskDetail;
  state: FieldState;
  onUpdate: IssueActions["onUpdate"];
}) {
  const colors = new Map(card.labelPalette.map((l) => [l.name, l.color]));
  const { busy, notes } = state;

  return (
    <PropertyPanel>
      <Row label="Status">
        <Select
          value={card.status}
          disabled={busy.status}
          onValueChange={(status) =>
            onUpdate("status", { status }, (c) => ({ ...c, status: status as TaskDetail["status"] }))
          }
        >
          <SelectTrigger size="sm" className="w-full" aria-label="Status">
            <SelectValue />
          </SelectTrigger>
          <SelectContent>
            {STATUSES.map((s) => (
              <SelectItem key={s} value={s}>
                <StatusIcon status={s} />
                {STATUS_META[s].label}
              </SelectItem>
            ))}
          </SelectContent>
        </Select>
        <FieldNote busy={busy.status} note={notes.status} />
      </Row>

      <Row label="Priority">
        <Select
          value={card.priority}
          disabled={busy.priority}
          onValueChange={(priority) =>
            onUpdate("priority", { priority }, (c) => ({ ...c, priority: priority as TaskDetail["priority"] }))
          }
        >
          <SelectTrigger size="sm" className="w-full" aria-label="Priority">
            <SelectValue />
          </SelectTrigger>
          <SelectContent>
            {PRIORITIES.map((p) => (
              <SelectItem key={p} value={p}>
                <PriorityIcon priority={p} />
                {PRIORITY_META[p].label}
              </SelectItem>
            ))}
          </SelectContent>
        </Select>
        <FieldNote busy={busy.priority} note={notes.priority} />
      </Row>

      <Row label="Assignee">
        <Select
          value={card.assignee?.id ?? UNASSIGNED}
          disabled={busy.assignee}
          onValueChange={(id) => {
            const person = card.people.find((p) => p.id === id) ?? null;
            onUpdate("assignee", { assignee: person ? person.id : null }, (c) => ({ ...c, assignee: person }));
          }}
        >
          <SelectTrigger size="sm" className="w-full" aria-label="Assignee">
            <SelectValue />
          </SelectTrigger>
          <SelectContent>
            <SelectItem value={UNASSIGNED}>
              <PersonAvatar person={null} className="size-4" />
              Unassigned
            </SelectItem>
            {(["human", "agent"] as const).map((kind) => (
              <SelectGroup key={kind}>
                <SelectSeparator />
                <SelectLabel>{kind === "human" ? "People" : "Agents"}</SelectLabel>
                {card.people
                  .filter((p) => p.kind === kind)
                  .map((p) => (
                    <SelectItem key={p.id} value={p.id}>
                      <PersonAvatar person={p} className="size-4" />
                      {p.name}
                    </SelectItem>
                  ))}
              </SelectGroup>
            ))}
          </SelectContent>
        </Select>
        <FieldNote busy={busy.assignee} note={notes.assignee} />
      </Row>

      <Row label="Due date">
        <div className="flex items-center gap-1">
          <Input
            type="date"
            value={card.dueDate ?? ""}
            disabled={busy.due}
            aria-label="Due date"
            aria-invalid={card.overdue || undefined}
            className="tabular h-8 flex-1 text-[13px] aria-invalid:text-danger"
            onChange={(event) => {
              const due = event.target.value;
              if (due && !/^\d{4}-\d{2}-\d{2}$/.test(due)) return;
              onUpdate("due", { due: due || null }, (c) => ({ ...c, dueDate: due || null, overdue: false }));
            }}
          />
          {card.dueDate && (
            <Button
              variant="ghost"
              size="icon"
              className="text-muted-foreground size-8"
              aria-label="Clear due date"
              disabled={busy.due}
              onClick={() => onUpdate("due", { due: null }, (c) => ({ ...c, dueDate: null, overdue: false }))}
            >
              <X />
            </Button>
          )}
        </div>
        {card.overdue && !busy.due && <p className="text-danger text-[11px]">Overdue</p>}
        <FieldNote busy={busy.due} note={notes.due} />
      </Row>

      <Row label="Estimate">
        <PropertyValue className="tabular">
          {card.estimate === null ? (
            <span className="text-subtle-foreground">None</span>
          ) : (
            `${card.estimate} ${card.estimate === 1 ? "point" : "points"}`
          )}
        </PropertyValue>
      </Row>

      <Row label="Labels">
        <div className="flex flex-wrap gap-1 pt-1">
          {card.labels.length ? (
            card.labels.map((label) => <LabelChip key={label} name={label} color={colors.get(label)} />)
          ) : (
            <span className="text-subtle-foreground text-[13px]">None</span>
          )}
        </div>
      </Row>

      <PropertyFooter>
        <span className="flex min-w-0 items-center gap-1.5">
          Created by <PersonName person={card.creator} className="text-foreground" />
        </span>
        <span title={formatDateTime(card.createdAt)}>Created {timeAgo(card.createdAt, card.now)}</span>
        <span title={formatDateTime(card.updatedAt)}>Updated {timeAgo(card.updatedAt, card.now)}</span>
      </PropertyFooter>
    </PropertyPanel>
  );
}
