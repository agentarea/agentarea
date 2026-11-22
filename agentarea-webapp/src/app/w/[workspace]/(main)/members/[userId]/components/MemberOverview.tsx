import type { PolicyRuleResponse, TaskWithAgent } from "@/api/client/types.gen";
import {
  getAllTasks,
  listAccessControlRelationships,
  listPolicies,
  resolvePrincipals,
} from "@/lib/api";
import { getViewerCapabilities } from "@/lib/workspace-context";
import { fetchAuditLogs } from "../../../settings/audit/actions";
import {
  getMemberAccess,
  getMemberSecondaryLabel,
} from "../../components/membersShared";
import { getMemberCached, getMemberTriggersCached } from "../memberDetail";
import {
  latestInstant,
  memberGrants,
  summarizeMemberTasks,
} from "../memberStats";
import {
  MemberOverviewView,
  type MemberOverviewModel,
} from "./MemberOverviewView";

/** Tasks the stats are computed over; past it the figures say "newest N". */
const TASK_SAMPLE = 100;
const RECENT_TASKS = 5;

/** Who sent the invitation this member joined through, from the audit trail. */
async function loadInviter(invitationId: string) {
  const { data } = await fetchAuditLogs({
    action: "member.invite",
    resource_type: "invitation",
    resource_id: invitationId,
    limit: 1,
  });
  const actorId = data?.events[0]?.actor_id;
  if (!actorId) return null;
  const principals = await resolvePrincipals([actorId]);
  const name = principals.data?.find((p) => p.id === actorId)?.display_name;
  return { id: actorId, name: name ?? null };
}

/**
 * Data container for a member's overview: who they are, what they started,
 * what runs on their authority and which rules name them. Supporting sections
 * degrade on failure instead of taking the page down.
 */
export async function MemberOverview({ userId }: { userId: string }) {
  const loaded = await getMemberCached(userId);
  const { member, currentUser, ownerUserId } = loaded;
  const { canAdminister } = await getViewerCapabilities();

  const isSelf = member.user_id === currentUser.id;

  const [tasksRes, triggers, policiesRes, lastAudit, inviter, grantsRes] =
    await Promise.all([
      getAllTasks({ created_by: member.user_id, limit: TASK_SAMPLE + 1 }),
      getMemberTriggersCached(member.user_id),
      listPolicies({ subject_type: "user", subject_id: member.user_id }),
      canAdminister
        ? fetchAuditLogs({ actor_id: member.user_id, limit: 1 })
        : null,
      canAdminister && member.invitation_id
        ? loadInviter(member.invitation_id)
        : null,
      // The grant list is admin-only; members don't ask for a 403.
      canAdminister ? listAccessControlRelationships() : null,
    ]);

  if (tasksRes.error) {
    console.error("Failed to load a member's tasks", tasksRes.error);
  }
  if (grantsRes?.error) {
    console.error("Failed to load a member's grants", grantsRes.error);
  }
  if (policiesRes.error) {
    console.error("Failed to load a member's policy rules", policiesRes.error);
  }

  const tasks = tasksRes.error
    ? null
    : ((tasksRes.data ?? []) as TaskWithAgent[]);
  const summary = tasks ? summarizeMemberTasks(tasks, TASK_SAMPLE) : null;
  const lastAuditAt = lastAudit?.data?.events[0]?.created_at ?? null;

  const model: MemberOverviewModel = {
    userId: member.user_id,
    label: loaded.label,
    secondary: getMemberSecondaryLabel(member, currentUser),
    isSelf,
    access: getMemberAccess(member, ownerUserId),
    joinedAt: member.joined_at ?? null,
    joinedViaInvitation: Boolean(member.invitation_id),
    inviter,
    canSeeAudit: canAdminister,
    tasks: summary
      ? { summary, recent: (tasks ?? []).slice(0, RECENT_TASKS) }
      : null,
    automations: triggers,
    policies: policiesRes.error
      ? null
      : ((policiesRes.data ?? []) as PolicyRuleResponse[]),
    grants: !grantsRes
      ? undefined
      : grantsRes.error || !grantsRes.data
        ? null
        : memberGrants(grantsRes.data.relationships, member.user_id),
    lastActiveAt: latestInstant(summary?.lastStartedAt, lastAuditAt),
  };

  return <MemberOverviewView model={model} />;
}
