import type { ReactNode } from "react";
import { useTranslations } from "next-intl";
import { GitFork, Zap } from "lucide-react";
import type { TaskProvenance } from "@/api/client/types.gen";
import { AgentAvatar } from "@/components/AgentAvatar";
import { InfoPanelRow } from "@/components/InfoPanel";
import { BlueprintBadge } from "@/components/ui/blueprint-badge";
import { EntityAvatar, nameInitials } from "@/components/ui/entity-avatar";
import { deterministicHue } from "@/lib/avatar-hue";
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
  /** Open `href` in a new browser tab, leaving the task where it is. */
  newTab?: boolean;
  title?: string;
}

function ParticipantRow({ participant }: { participant: Participant }) {
  return (
    <InfoPanelRow
      avatar={participant.avatar}
      name={participant.name}
      badge={participant.badge}
      sub={participant.role}
      href={participant.href}
      newTab={participant.newTab}
      title={participant.title}
    />
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
    // The agent's page is a detour from the run: the task stays open.
    newTab: true,
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
