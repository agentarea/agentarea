"use client";

import { useTranslations } from "next-intl";
import { ArrowDownAZ, Clock, Link2, Mail, Shield, Users } from "lucide-react";
import DisplayMenu from "@/components/DisplayMenu";
import SearchInput from "@/components/SearchInput";
import SubheaderToolbar from "@/components/SubheaderToolbar";
import { CountSegmentedControl } from "@/components/ui/count-segmented-control";
import { MenuRow, MenuSectionLabel } from "@/components/ui/menu-row";
import type {
  InvitationsOrder,
  MembersOrder,
  MembersTab,
} from "./membersShared";

interface MembersToolbarProps {
  tab: MembersTab;
  onTabChange: (tab: MembersTab) => void;
  counts: Record<MembersTab, number>;
  showInvitations: boolean;
  onQueryChange: (query: string) => void;
  order: MembersOrder;
  onOrderChange: (order: MembersOrder) => void;
  invitationsOrder: InvitationsOrder;
  onInvitationsOrderChange: (order: InvitationsOrder) => void;
}

/**
 * Members page subheader: Members / Invitations switcher with counts, a
 * client-side search box and the "Display" ordering menu.
 */
export function MembersToolbar({
  tab,
  onTabChange,
  counts,
  showInvitations,
  onQueryChange,
  order,
  onOrderChange,
  invitationsOrder,
  onInvitationsOrderChange,
}: MembersToolbarProps) {
  const t = useTranslations("MembersPage");

  return (
    <SubheaderToolbar
      categories={
        <CountSegmentedControl<MembersTab>
          items={[
            {
              value: "members",
              label: (
                <span className="flex items-center gap-1.5 whitespace-nowrap">
                  <Users className="h-4 w-4" strokeWidth={1.8} />
                  {t("tabMembers")}
                </span>
              ),
              count: counts.members,
            },
            ...(showInvitations
              ? [
                  {
                    value: "invitations" as const,
                    label: (
                      <span className="flex items-center gap-1.5 whitespace-nowrap">
                        <Link2 className="h-4 w-4" strokeWidth={1.8} />
                        {t("tabInvitations")}
                      </span>
                    ),
                    count: counts.invitations,
                  },
                ]
              : []),
          ]}
          value={tab}
          onChange={onTabChange}
          layoutId="members-tab-control"
        />
      }
      search={
        <SearchInput
          delay={250}
          placeholder={t("searchPlaceholder")}
          onDebouncedChange={onQueryChange}
        />
      }
      controls={
        <DisplayMenu>
          <MenuSectionLabel>{t("ordering")}</MenuSectionLabel>
          {tab === "members" ? (
            <>
              <MenuRow
                icon={<Shield className="h-3.5 w-3.5" />}
                label={t("orderAccess")}
                selected={order === "access"}
                onClick={() => onOrderChange("access")}
              />
              <MenuRow
                icon={<ArrowDownAZ className="h-3.5 w-3.5" />}
                label={t("orderUserId")}
                selected={order === "id"}
                onClick={() => onOrderChange("id")}
              />
            </>
          ) : (
            <>
              <MenuRow
                icon={<Clock className="h-3.5 w-3.5" />}
                label={t("orderExpires")}
                selected={invitationsOrder === "expires"}
                onClick={() => onInvitationsOrderChange("expires")}
              />
              <MenuRow
                icon={<Mail className="h-3.5 w-3.5" />}
                label={t("orderRecipient")}
                selected={invitationsOrder === "recipient"}
                onClick={() => onInvitationsOrderChange("recipient")}
              />
            </>
          )}
        </DisplayMenu>
      }
    />
  );
}
