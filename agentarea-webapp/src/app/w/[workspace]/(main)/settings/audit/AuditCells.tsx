"use client";

import { createElement } from "react";
import { useTranslations } from "next-intl";
import { Activity } from "lucide-react";
import { BlueprintBadge } from "@/components/ui/blueprint-badge";
import { EntityAvatar, nameInitials } from "@/components/ui/entity-avatar";
import Link from "@/components/WorkspaceLink";
import { deterministicHue } from "@/lib/avatar-hue";
import type { AuditEvent } from "./actions";
import { auditActorIcon, auditResourceIcon, auditVerbIcon } from "./auditIcons";
import { auditVerb, auditVerbTone } from "./format";

const LINK = "truncate";

/** What happened: a tinted glyph and the verb in words; the raw action on hover. */
export function AuditAction({ action }: { action: string }) {
  const t = useTranslations("AuditLogPage.verbs");
  const verb = auditVerb(action);
  const glyph = auditVerbIcon(verb) ?? Activity;

  return (
    <span className="inline-flex min-w-0 items-center gap-2" title={action}>
      <EntityAvatar
        size={22}
        variant="soft"
        color={auditVerbTone(action)}
        icon={createElement(glyph, { strokeWidth: 2 })}
        iconScale={0.6}
        aria-hidden
      />
      <span className="truncate text-[12.5px] font-medium">
        {t.has(verb) ? t(verb) : verb}
      </span>
    </span>
  );
}

/** Who did it: a person's coloured initials, an agent's neutral tile, or a key. */
export function AuditActor({ event }: { event: AuditEvent }) {
  const t = useTranslations("AuditLogPage");
  const actor = event.actor;
  const type = actor?.actor_type ?? event.actor_type ?? "user";
  const isMe = Boolean(actor?.is_current_user);
  const name = isMe
    ? actor?.description || actor?.label
    : (actor?.label ?? event.actor_id);
  const secondary = isMe ? null : actor?.description;
  const glyph = createElement(auditActorIcon(type), { strokeWidth: 1.85 });

  return (
    <span className="flex min-w-0 items-center gap-2.5">
      {type === "user" ? (
        <EntityAvatar
          size={24}
          variant="pigment"
          hue={deterministicHue(event.actor_id)}
          text={nameInitials(name ?? "")}
          aria-hidden
        />
      ) : type === "agent" ? (
        <EntityAvatar
          size={24}
          hue={deterministicHue(event.actor_id)}
          icon={glyph}
          aria-hidden
        />
      ) : (
        <EntityAvatar size={24} variant="soft" icon={glyph} aria-hidden />
      )}
      <span className="flex min-w-0 flex-col">
        <span className="flex min-w-0 items-center gap-2 text-[13px] font-medium">
          {actor?.href ? (
            <Link
              href={actor.href}
              className={LINK}
              onClick={(e) => e.stopPropagation()}
            >
              {name}
            </Link>
          ) : (
            <span className="truncate">{name}</span>
          )}
          {isMe && <BlueprintBadge>{t("you")}</BlueprintBadge>}
        </span>
        {secondary && (
          <span className="truncate text-xs text-muted-foreground">
            {secondary}
          </span>
        )}
      </span>
    </span>
  );
}

/**
 * What it happened to: the thing's tile, its name, and its kind with a short
 * id. Not a link itself: in the table the whole row leads to the resource.
 */
export function AuditResource({ event }: { event: AuditEvent }) {
  const resource = event.resource;
  const label = resource?.label ?? event.resource_type;
  const typeLabel = resource?.type_label ?? event.resource_type;
  const glyph = auditResourceIcon(event.resource_type) ?? Activity;
  const id = event.resource_id;
  // The second line says only what the name does not: a resource with no
  // name of its own is already called "<Type> <short id>", or just "<Type>".
  const showType = !label.startsWith(typeLabel);
  const showId = Boolean(id) && !label.includes(id?.slice(0, 8) ?? "");

  return (
    <span className="flex min-w-0 items-center gap-2.5">
      <EntityAvatar
        size={28}
        hue={deterministicHue(event.resource_type)}
        icon={createElement(glyph, { strokeWidth: 1.85 })}
        aria-hidden
      />
      <span className="flex min-w-0 flex-col">
        <span
          className="min-w-0 truncate text-[13px] font-medium"
          title={id ?? undefined}
        >
          {label}
        </span>
        {(showType || showId) && (
          <span className="truncate text-xs text-muted-foreground">
            {showType && typeLabel}
            {showType && showId && " · "}
            {showId && (
              <span className="font-mono">
                {resource?.found ? id?.slice(0, 8) : id}
              </span>
            )}
          </span>
        )}
      </span>
    </span>
  );
}
