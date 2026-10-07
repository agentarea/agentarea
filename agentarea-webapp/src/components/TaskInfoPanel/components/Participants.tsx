import type { ReactNode } from "react";
import { useTranslations } from "next-intl";
import { ArrowUpRight, GitFork, Zap } from "lucide-react";
import type { TaskProvenance } from "@/api/client/types.gen";
import { AgentAvatar } from "@/components/AgentAvatar";
import { BlueprintBadge } from "@/components/ui/blueprint-badge";
import { EntityAvatar, nameInitials } from "@/components/ui/entity-avatar";
import Link from "@/components/WorkspaceLink";
import { deterministicHue } from "@/lib/avatar-hue";
import { cn } from "@/lib/utils";
import type { TaskRequester } from "../types";
import Section from "./Section";

const AVATAR_SIZE = 20;

interface ParticipantsProps {
  agentId: string;
  agentName?: string | null;
  delegatedAgents?: string[];
  /** Who or what started this task — a trigger, a delegating task, or (the
   * default) a person. */
  provenance?: TaskProvenance | null;
  /** The person `created_by` names; null when the task names nobody. */
  requester?: TaskRequester | null;
}

interface Participant {
  avatar: ReactNode;
  name: string;
  /** Next to the name, e.g. "You". */
  badge?: ReactNode;
  role: string;
  /** Present for a related resource (the agent, the trigger, the delegating
   * task) — the row links there instead of just sitting flat. */
  href?: string;
  title?: string;
}

/**
 * One participant: tile, name, role. A row that leads somewhere is lit as a
 * whole on hover, as list rows inside a panel are, with the arrow saying it
 * opens another page — not an underlined name.
 */
function ParticipantRow({ participant }: { participant: Participant }) {
  const body = (
    <>
      {participant.avatar}
      <span className="min-w-0 flex-1">
        <span className="flex min-w-0 items-center gap-1.5">
          <span className="truncate text-[12px] font-medium text-foreground">
            {participant.name}
          </span>
          {participant.badge}
        </span>
        <span className="block truncate text-[10px] text-muted-foreground">
          {participant.role}
        </span>
      </span>
    </>
  );
  const rowClassName = "-mx-1.5 flex items-center gap-2 rounded-md px-1.5 py-1";

  if (!participant.href) {
    return (
      <div className={rowClassName} title={participant.title}>
        {body}
      </div>
    );
  }

  return (
    <Link
      href={participant.href}
      title={participant.title}
      className={cn(
        rowClassName,
        "group/participant transition-colors hover:bg-muted/40 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring"
      )}
    >
      {body}
      <ArrowUpRight
        aria-hidden
        strokeWidth={1.5}
        className="h-3.5 w-3.5 shrink-0 text-muted-foreground opacity-0 transition-opacity group-hover/participant:opacity-100 group-focus-visible/participant:opacity-100"
      />
    </Link>
  );
}

/**
 * The person who asked for the run: their initials and name, marked "You"
 * when that is the viewer. Not a link: there is no page about a person worth
 * leaving the task for. An id nothing resolves is labelled as unknown, keeping
 * the id in the tooltip.
 */
function personFrom(
  requester: TaskRequester,
  t: ReturnType<typeof useTranslations>,
  tTasks: ReturnType<typeof useTranslations>
): Participant {
  const badge = requester.isCurrentUser ? (
    <BlueprintBadge>{t("you")}</BlueprintBadge>
  ) : undefined;

  if (!requester.name) {
    return {
      avatar: (
        <EntityAvatar size={AVATAR_SIZE} variant="soft" text="?" aria-hidden />
      ),
      name: tTasks("unknownCreator"),
      badge,
      role: t("roleRequester"),
      title: requester.id,
    };
  }

  const name = requester.name;
  // Only the local part of an email carries a name — the domain would turn
  // alice@example.com into "AE".
  const initials = nameInitials(
    name.includes("@") ? name.slice(0, name.indexOf("@")) : name
  );
  return {
    avatar: (
      <EntityAvatar
        size={AVATAR_SIZE}
        variant="pigment"
        hue={deterministicHue(requester.id)}
        text={initials}
        aria-hidden
      />
    ),
    name,
    badge,
    role: t("roleRequester"),
  };
}

/**
 * Who asked for this run, from its provenance. A trigger or a delegating
 * task started it, not a person — each links to the thing that started it.
 * Neither the trigger nor the task has a resolved name available here (the
 * provenance carries only ids), so the link is labelled by what it is,
 * matching how the rest of this panel names an id-only related resource
 * (`Metadata`'s own "Parent Task" field does the same). The causing event
 * itself has no link: provenance only carries the event's id, and there is no
 * lookup from an event id to the stream and sequence that would resolve (see
 * the UX polish report, U10).
 */
function requesterFrom(
  provenance: TaskProvenance | null | undefined,
  requester: TaskRequester | null | undefined,
  t: ReturnType<typeof useTranslations>,
  tTasks: ReturnType<typeof useTranslations>
): Participant | null {
  if (provenance?.origin_type === "trigger" && provenance.origin_id) {
    return {
      avatar: (
        <EntityAvatar
          size={AVATAR_SIZE}
          hue={deterministicHue(provenance.origin_id)}
          icon={<Zap strokeWidth={1.85} />}
          aria-hidden
        />
      ),
      name: t("roleTrigger"),
      role: t("startedBy"),
      href: `/triggers/${provenance.origin_id}`,
    };
  }
  const parentTaskId = provenance?.parent_task_id || provenance?.origin_id;
  if (provenance?.origin_type === "agent" && parentTaskId) {
    return {
      avatar: (
        <EntityAvatar
          size={AVATAR_SIZE}
          variant="soft"
          icon={<GitFork strokeWidth={1.85} />}
          aria-hidden
        />
      ),
      name: t("roleDelegatingTask"),
      role: t("startedBy"),
      href: `/tasks/${parentTaskId}`,
    };
  }
  // A task that names nobody gets no requester row: claiming "You" for it
  // would be a guess.
  return requester ? personFrom(requester, t, tTasks) : null;
}

export default function Participants({
  agentId,
  agentName,
  delegatedAgents,
  provenance,
  requester,
}: ParticipantsProps) {
  const t = useTranslations("TaskInfoPanel");
  const tTasks = useTranslations("TasksPage");

  const started = requesterFrom(provenance, requester, t, tTasks);
  const agent: Participant = {
    avatar: (
      <AgentAvatar
        agent={{ id: agentId, name: agentName || t("agent") }}
        size="xs"
      />
    ),
    name: agentName || t("agent"),
    role: t("rolePrimaryAgent"),
    href: `/agents/${agentId}`,
  };
  const delegated: Participant[] = (delegatedAgents || []).map((name) => ({
    avatar: (
      <EntityAvatar
        size={AVATAR_SIZE}
        variant="soft"
        icon={<GitFork strokeWidth={1.85} />}
        aria-hidden
      />
    ),
    name,
    role: t("roleDelegated"),
  }));

  return (
    <Section title={t("participants")} contentClassName="space-y-0.5 text-xs">
      {started && <ParticipantRow participant={started} />}
      <ParticipantRow participant={agent} />
      {delegated.map((participant, index) => (
        <ParticipantRow
          key={`${participant.name}-${index}`}
          participant={participant}
        />
      ))}
    </Section>
  );
}
