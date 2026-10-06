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

const LINK = "truncate underline-offset-2 hover:text-primary hover:underline";

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

/** What it happened to: the thing's tile, its name, and its kind with a short id. */
export function AuditResource({ event }: { event: AuditEvent }) {
  const resource = event.resource;
  const label = resource?.label ?? event.resource_type;
  const typeLabel = resource?.type_label ?? event.resource_type;
  const glyph = auditResourceIcon(event.resource_type) ?? Activity;
  const id = event.resource_id;

  return (
    <span className="flex min-w-0 items-center gap-2.5">
      <EntityAvatar
        size={28}
        hue={deterministicHue(event.resource_type)}
        icon={createElement(glyph, { strokeWidth: 1.85 })}
        aria-hidden
      />
      <span className="flex min-w-0 flex-col">
        <span className="min-w-0 truncate text-[13px] font-medium">
          {resource?.href ? (
            <Link
              href={resource.href}
              className={LINK}
              onClick={(e) => e.stopPropagation()}
            >
              {label}
            </Link>
          ) : (
            label
          )}
        </span>
        <span className="truncate text-xs text-muted-foreground">
          {typeLabel}
          {id && (
            <>
              {" · "}
              <span className="font-mono" title={id}>
                {resource?.found ? id.slice(0, 8) : id}
              </span>
            </>
          )}
        </span>
      </span>
    </span>
  );
}
