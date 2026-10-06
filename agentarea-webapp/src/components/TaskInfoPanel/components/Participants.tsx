import { useTranslations } from "next-intl";
import { GitFork, User, Zap } from "lucide-react";
import type { TaskProvenance } from "@/api/client/types.gen";
import { AgentLink } from "@/components/AgentIdentity";
import Link from "@/components/WorkspaceLink";
import Section from "./Section";

interface ParticipantsProps {
  agentId: string;
  agentName?: string | null;
  delegatedAgents?: string[];
  /** Who or what started this task — a trigger, a delegating task, or (the
   * default) a person. */
  provenance?: TaskProvenance | null;
}

interface Participant {
  name: string;
  role: string;
  icon: typeof User;
  iconClass: string;
  /** Present for a related resource (the trigger, the delegating task) —
   * the row links there instead of just sitting flat. */
  href?: string;
}

function ParticipantRow({ participant }: { participant: Participant }) {
  const Icon = participant.icon;
  const body = (
    <div className="flex items-center gap-2 px-0.5 py-1">
      <Icon className={`h-4 w-4 shrink-0 ${participant.iconClass}`} />
      <div className="min-w-0 flex-1">
        <div
          className={`truncate text-[12px] font-medium text-foreground ${
            participant.href ? "hover:underline" : ""
          }`}
        >
          {participant.name}
        </div>
        <div className="truncate text-[10px] text-muted-foreground">
          {participant.role}
        </div>
      </div>
    </div>
  );

  return participant.href ? (
    <Link href={participant.href} className="block">
      {body}
    </Link>
  ) : (
    body
  );
}

/**
 * Who asked for this run, from its provenance. A trigger or a delegating
 * task started it, not the viewer, so "You" would be wrong there — each
 * links to the thing that started it. Neither the trigger nor the task has a
 * resolved name available here (the provenance carries only ids), so the
 * link is labelled by what it is, matching how the rest of this panel names
 * an id-only related resource (`Metadata`'s own "Parent Task" field does the
 * same). The causing event itself has no link: provenance only carries the
 * event's id, and there is no lookup from an event id to the stream and
 * sequence that would resolve (see the UX polish report, U10).
 */
function requesterFrom(
  provenance: TaskProvenance | null | undefined,
  t: ReturnType<typeof useTranslations>
): Participant {
  if (provenance?.origin_type === "trigger" && provenance.origin_id) {
    return {
      name: t("roleTrigger"),
      role: t("startedBy"),
      icon: Zap,
      iconClass: "text-amber-600 dark:text-amber-400",
      href: `/triggers/${provenance.origin_id}`,
    };
  }
  const parentTaskId = provenance?.parent_task_id || provenance?.origin_id;
  if (provenance?.origin_type === "agent" && parentTaskId) {
    return {
      name: t("roleDelegatingTask"),
      role: t("startedBy"),
      icon: GitFork,
      iconClass: "text-sky-600 dark:text-sky-400",
      href: `/tasks/${parentTaskId}`,
    };
  }
  return {
    name: t("you"),
    role: t("roleRequester"),
    icon: User,
    iconClass: "text-zinc-500",
  };
}

export default function Participants({
  agentId,
  agentName,
  delegatedAgents,
  provenance,
}: ParticipantsProps) {
  const t = useTranslations("TaskInfoPanel");

  const requester = requesterFrom(provenance, t);
  const delegated: Participant[] = (delegatedAgents || []).map((name) => ({
    name,
    role: t("roleDelegated"),
    icon: GitFork,
    iconClass: "text-sky-600 dark:text-sky-400",
  }));

  return (
    <Section title={t("participants")} contentClassName="space-y-1.5 text-xs">
      <ParticipantRow participant={requester} />
      <AgentLink
        agent={{ id: agentId, name: agentName || t("agent") }}
        size="xs"
        meta={t("rolePrimaryAgent")}
        className="w-full px-0.5 py-1"
        nameClassName="text-[12px]"
        metaClassName="text-[10px]"
      />
      {delegated.map((participant, index) => (
        <ParticipantRow
          key={`${participant.name}-${index}`}
          participant={participant}
        />
      ))}
    </Section>
  );
}
