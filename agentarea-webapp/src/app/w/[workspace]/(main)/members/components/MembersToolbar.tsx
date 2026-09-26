"use client";

import { useTranslations } from "next-intl";
import {
  ArrowDownAZ,
  Clock,
  Link2,
  Mail,
  Shield,
  SlidersHorizontal,
  Users,
} from "lucide-react";
import SearchInput from "@/components/SearchInput";
import { CountSegmentedControl } from "@/components/ui/count-segmented-control";
import { MenuRow, MenuSectionLabel } from "@/components/ui/menu-row";
import {
  Popover,
  PopoverContent,
  PopoverTrigger,
} from "@/components/ui/popover";
import { ToolbarButton, ToolbarDivider } from "@/components/ui/toolbar";
import type {
  InvitationsOrder,
  MembersOrder,
  MembersTab,
} from "./membersShared";

interface MembersToolbarProps {
  tab: MembersTab;
  onTabChange: (tab: MembersTab) => void;
  counts: Record<MembersTab, number>;
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
  onQueryChange,
  order,
  onOrderChange,
  invitationsOrder,
  onInvitationsOrderChange,
}: MembersToolbarProps) {
  const t = useTranslations("MembersPage");

  return (
    <div className="flex min-w-0 flex-1 items-center gap-1.5">
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
          {
            value: "invitations",
            label: (
              <span className="flex items-center gap-1.5 whitespace-nowrap">
                <Link2 className="h-4 w-4" strokeWidth={1.8} />
                {t("tabInvitations")}
              </span>
            ),
            count: counts.invitations,
          },
        ]}
        value={tab}
        onChange={onTabChange}
        layoutId="members-tab-control"
      />
      <ToolbarDivider />
      <div className="w-[280px] min-w-0 max-w-full">
        <SearchInput
          delay={250}
          placeholder={t("searchPlaceholder")}
          onDebouncedChange={onQueryChange}
        />
      </div>
      <div className="flex-1" />
      {/* Same "Display" popover menu as the Skills page. */}
      <Popover>
        <PopoverTrigger asChild>
          <ToolbarButton>
            <SlidersHorizontal className="h-3.5 w-3.5 text-muted-foreground" />
            {t("display")}
          </ToolbarButton>
        </PopoverTrigger>
        <PopoverContent align="end" className="w-52 p-1.5">
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
        </PopoverContent>
      </Popover>
    </div>
  );
}
