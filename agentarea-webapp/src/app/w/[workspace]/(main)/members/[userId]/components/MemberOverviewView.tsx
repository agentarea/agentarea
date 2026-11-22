import { createElement } from "react";
import { getLocale, getTranslations } from "next-intl/server";
import {
  CalendarPlus,
  CircleAlert,
  Clock,
  Fingerprint,
  ListChecks,
  Mail,
  Shield,
  UserPlus,
  Wallet,
  Zap,
} from "lucide-react";
import type {
  PolicyRuleResponse,
  TaskWithAgent,
  TriggerResponse,
} from "@/api/client/types.gen";
import { formatRelTime } from "@/app/w/[workspace]/(main)/dashboard/components/relTime";
import {
  EmptyRow,
  FactRow,
  GlanceRow,
  HeroMeta,
  SectionCard,
  SectionCardHead,
  SoftTile,
  Stat,
  StatStrip,
} from "@/components/Overview/OverviewCard";
import { OverviewHero } from "@/components/Overview/OverviewHero";
import { OverviewTaskRow } from "@/components/Overview/OverviewTaskRow";
import SectionLoadError from "@/components/SectionLoadError";
import { Badge } from "@/components/ui/badge";
import { BlueprintBadge } from "@/components/ui/blueprint-badge";
import { EntityAvatar, nameInitials } from "@/components/ui/entity-avatar";
import { StatusIndicator } from "@/components/ui/status-indicator";
import { getPricingCurrency } from "@/lib/api-dashboard";
import { deterministicHue } from "@/lib/avatar-hue";
import { ENTITY_ICONS } from "@/lib/entity-icons";
import { formatMoney } from "@/lib/money";
import { getTriggerStatusPresentation } from "@/lib/status";
import { formatDate } from "@/utils/dateUtils";
import { getTriggerHealth } from "../../../triggers/components/triggerDisplay";
import { shortId, type MemberAccess } from "../../components/membersShared";
import type { MemberGrant, MemberTaskSummary } from "../memberStats";

/** Everything the member overview renders, resolved by {@link MemberOverview}. */
export type MemberOverviewModel = {
  userId: string;
  label: string;
  secondary: string | null;
  isSelf: boolean;
  access: MemberAccess;
  joinedAt: string | null;
  joinedViaInvitation: boolean;
  /** Null when unknown or not looked up (the audit trail is admin-only). */
  inviter: { id: string; name: string | null } | null;
  canSeeAudit: boolean;
  /** Null when the tasks could not be loaded. */
  tasks: { summary: MemberTaskSummary; recent: TaskWithAgent[] } | null;
  automations: TriggerResponse[] | null;
  policies: PolicyRuleResponse[] | null;
  /** Resources granted to them directly; undefined when not looked up
   * (admin-only), null when the lookup failed. */
  grants?: MemberGrant[] | null;
  lastActiveAt: string | null;
};

/** Grants listed before the card defers to the access view. */
const GRANTS_SHOWN = 8;

const GRANT_ICON = {
  Agent: ENTITY_ICONS.agent,
  MCPServer: ENTITY_ICONS.mcp,
  Skill: ENTITY_ICONS.skill,
  SkillCollection: ENTITY_ICONS.skill,
} as const;

function grantIcon(namespace: string) {
  return GRANT_ICON[namespace as keyof typeof GRANT_ICON] ?? ENTITY_ICONS.tool;
}

function GrantRow({ grant, t }: { grant: MemberGrant; t: Translator }) {
  const props = {
    tile: <SoftTile icon={createElement(grantIcon(grant.namespace))} />,
    title: grant.objectName,
    sub: t(
      `grantKind.${grant.namespace in GRANT_ICON ? grant.namespace : "other"}`
    ),
    trailing: (
      <span className="text-[12px] font-medium text-foreground/80">
        {t(`grantRelation.${grant.relation}`)}
      </span>
    ),
  };
  return grant.namespace === "Agent" ? (
    <GlanceRow href={`/agents/${grant.object}`} {...props} />
  ) : (
    <FactRow {...props} />
  );
}

type Translator = Awaited<ReturnType<typeof getTranslations>>;

const POLICY_EFFECTS = [
  "allow",
  "deny",
  "cap",
  "approval",
  "safety",
  "egress",
] as const;

function effectLabel(effect: string, t: Translator): string {
  return (POLICY_EFFECTS as readonly string[]).includes(effect)
    ? t(`effect.${effect}`)
    : effect;
}

function agoText(iso: string | null, t: Translator): string {
  const rel = formatRelTime(iso, t);
  if (!iso || rel === "—" || rel === t("relJustNow")) return rel;
  return t("agoFmt", { time: rel });
}

export async function MemberOverviewView({
  model,
}: {
  model: MemberOverviewModel;
}) {
  const [t, tMembers, tTrigger, locale, pricingCurrency] = await Promise.all([
    getTranslations("MembersPage.detail"),
    getTranslations("MembersPage"),
    getTranslations("TriggersPage.status"),
    getLocale(),
    getPricingCurrency(),
  ]);
  // Never guess a currency: a failed lookup renders the amount without one.
  const currency = pricingCurrency.ok ? pricingCurrency.currency : null;
  const money = (value: number) => formatMoney(value, currency, locale);

  const basePath = `/members/${encodeURIComponent(model.userId)}`;
  const summary = model.tasks?.summary ?? null;
  const countText = summary
    ? summary.capped
      ? `${summary.count}+`
      : String(summary.count)
    : "—";
  const lastActive = model.lastActiveAt
    ? formatRelTime(model.lastActiveAt, t)
    : null;
  const lastActiveIsNow = lastActive === t("relJustNow");
  const activeAutomations = (model.automations ?? []).filter(
    (trigger) => trigger.is_active
  );

  return (
    <div className="font-inter md:flex md:h-full md:min-h-0 md:flex-col md:overflow-hidden">
      <OverviewHero
        mark={
          <EntityAvatar
            size={34}
            variant="pigment"
            hue={deterministicHue(model.userId)}
            text={nameInitials(model.label)}
            className="mt-0.5 shrink-0"
            aria-hidden
          />
        }
        title={model.label}
        status={
          <span className="flex items-center gap-1.5">
            <Badge
              variant={model.access === "owner" ? "default" : "secondary"}
              title={
                model.access === "owner"
                  ? tMembers("accessOwnerHint")
                  : tMembers("accessMemberHint")
              }
            >
              {model.access === "owner"
                ? tMembers("accessOwner")
                : tMembers("accessMember")}
            </Badge>
            {model.isSelf && <BlueprintBadge>{tMembers("you")}</BlueprintBadge>}
          </span>
        }
        showMoreLabel={t("showMore")}
        showLessLabel={t("showLess")}
        meta={
          <>
            {model.secondary && (
              <HeroMeta icon={<Mail />}>
                <b className="font-medium text-foreground/80">
                  {model.secondary}
                </b>
              </HeroMeta>
            )}
            {model.joinedAt && (
              <HeroMeta icon={<CalendarPlus />}>
                {t("joinedOn", { date: formatDate(model.joinedAt, locale) })}
              </HeroMeta>
            )}
            {model.inviter ? (
              <HeroMeta icon={<UserPlus />}>
                {t("invitedBy")}{" "}
                <b className="font-medium text-foreground/80">
                  {model.inviter.name ?? shortId(model.inviter.id)}
                </b>
              </HeroMeta>
            ) : (
              !model.joinedViaInvitation &&
              model.access === "owner" && (
                <HeroMeta icon={<UserPlus />}>{t("createdWorkspace")}</HeroMeta>
              )
            )}
            <HeroMeta icon={<Fingerprint />}>
              <span className="font-mono" title={model.userId}>
                {shortId(model.userId)}
              </span>
            </HeroMeta>
          </>
        }
      />

      <div className="w-full bg-muted/20 px-4 pb-11 pt-[18px] md:min-h-0 md:flex-1 md:overflow-y-auto md:overscroll-contain">
        <StatStrip>
          <Stat
            icon={<ListChecks />}
            label={t("tasksStarted")}
            value={countText}
            bar={null}
            sub={
              !summary
                ? t("tasksUnavailable")
                : summary.count === 0
                  ? t("noTasksYet")
                  : t("runningNow", { count: summary.running })
            }
          />
          <Stat
            icon={<CircleAlert />}
            label={t("needsAction")}
            value={summary ? String(summary.needsAction) : "—"}
            bar={null}
            sub={t("needsActionHint")}
            subTone={summary && summary.needsAction > 0 ? "down" : "muted"}
          />
          <Stat
            icon={<Wallet />}
            label={t("spend")}
            value={summary ? money(summary.spend) : "—"}
            bar={null}
            sub={
              summary
                ? summary.capped
                  ? t("spendNewest", { count: summary.count })
                  : t("spendAcross", { count: summary.count })
                : t("tasksUnavailable")
            }
          />
          <Stat
            icon={<Clock />}
            label={t("lastActive")}
            value={lastActive ?? "—"}
            unit={lastActive && !lastActiveIsNow ? t("ago") : undefined}
            bar={null}
            sub={
              model.lastActiveAt
                ? formatDate(model.lastActiveAt, locale)
                : model.canSeeAudit
                  ? t("noActivity")
                  : t("lastActiveTasksOnly")
            }
          />
        </StatStrip>

        <div className="grid grid-cols-1 items-start gap-4 lg:grid-cols-[minmax(0,1.7fr)_minmax(0,1fr)]">
          <div className="flex min-w-0 flex-col gap-4">
            <SectionCard className="[&>a:last-child>div]:border-b-0">
              <SectionCardHead
                icon={<ListChecks />}
                title={t("recentTasks")}
                link={
                  summary && summary.count > 0
                    ? { label: t("allTasks"), href: `${basePath}/tasks` }
                    : undefined
                }
              />
              {!model.tasks ? (
                <SectionLoadError message={t("tasksUnavailable")} />
              ) : model.tasks.recent.length === 0 ? (
                <EmptyRow
                  text={model.isSelf ? t("noTasksSelf") : t("noTasksOther")}
                />
              ) : (
                model.tasks.recent.map((task) => {
                  const cost = Number(task.total_cost ?? 0);
                  return (
                    <OverviewTaskRow
                      key={task.id}
                      task={task}
                      sub={task.agent_name}
                      timeText={agoText(task.created_at, t)}
                      costText={cost > 0 ? money(cost) : "—"}
                    />
                  );
                })
              )}
            </SectionCard>
          </div>

          <div className="flex min-w-0 flex-col gap-4">
            <SectionCard className="[&>div:last-child]:border-b-0">
              <SectionCardHead
                icon={<Shield />}
                title={t("access")}
                link={{ label: t("policies"), href: "/policies" }}
              />
              <FactRow
                tile={<SoftTile icon={<Shield />} />}
                title={
                  model.access === "owner"
                    ? tMembers("accessOwner")
                    : tMembers("accessMember")
                }
                sub={
                  model.access === "owner"
                    ? tMembers("accessOwnerHint")
                    : tMembers("accessMemberHint")
                }
              />
              {model.policies === null ? (
                <SectionLoadError message={t("policiesUnavailable")} />
              ) : model.policies.length === 0 ? (
                <FactRow
                  title={t("noPersonalRules")}
                  sub={t("noPersonalRulesHint")}
                />
              ) : (
                model.policies.map((rule) => (
                  <FactRow
                    key={rule.id}
                    title={effectLabel(rule.effect, t)}
                    sub={<span className="font-mono">{rule.target}</span>}
                    trailing={
                      <StatusIndicator
                        kind={rule.enabled ? "active" : "off"}
                        size="sm"
                      >
                        {rule.enabled ? t("ruleOn") : t("ruleOff")}
                      </StatusIndicator>
                    }
                  />
                ))
              )}
            </SectionCard>

            {model.grants !== undefined && (
              <SectionCard className="[&>a:last-child>div]:border-b-0 [&>div:last-child]:border-b-0">
                <SectionCardHead
                  icon={<ENTITY_ICONS.person />}
                  title={t("directAccess")}
                  count={model.grants?.length}
                  link={{
                    label: t("accessView"),
                    href: "/policies?view=access",
                  }}
                />
                {model.grants === null ? (
                  <SectionLoadError message={t("grantsUnavailable")} />
                ) : model.grants.length === 0 ? (
                  <EmptyRow text={t("noGrants")} />
                ) : (
                  <>
                    {model.grants.slice(0, GRANTS_SHOWN).map((grant) => (
                      <GrantRow
                        key={`${grant.namespace}:${grant.object}`}
                        grant={grant}
                        t={t}
                      />
                    ))}
                    {model.grants.length > GRANTS_SHOWN && (
                      <FactRow
                        title={t("moreGrants", {
                          count: model.grants.length - GRANTS_SHOWN,
                        })}
                      />
                    )}
                  </>
                )}
              </SectionCard>
            )}

            <SectionCard className="[&>a:last-child>div]:border-b-0">
              <SectionCardHead
                icon={<Zap />}
                title={t("automations")}
                count={model.automations?.length}
              />
              {model.automations === null ? (
                <SectionLoadError message={t("automationsUnavailable")} />
              ) : model.automations.length === 0 ? (
                <EmptyRow text={t("noAutomations")} />
              ) : (
                <>
                  {activeAutomations.length > 0 && (
                    <p className="m-0 border-b border-border/60 px-[15px] py-2 text-[11px] text-muted-foreground">
                      {model.isSelf
                        ? t("automationsOutliveSelf")
                        : t("automationsOutlive", { member: model.label })}
                    </p>
                  )}
                  {model.automations.map((trigger) => {
                    const status = getTriggerStatusPresentation(
                      getTriggerHealth(trigger)
                    );
                    return (
                      <GlanceRow
                        key={trigger.id}
                        href={`/triggers/${trigger.id}`}
                        tile={<SoftTile icon={<Zap />} />}
                        title={trigger.name}
                        sub={trigger.description || trigger.trigger_type}
                        trailing={
                          <StatusIndicator kind={status.kind} size="sm">
                            {status.labelKey
                              ? tTrigger(status.labelKey)
                              : status.label}
                          </StatusIndicator>
                        }
                      />
                    );
                  })}
                </>
              )}
            </SectionCard>
          </div>
        </div>
      </div>
    </div>
  );
}
