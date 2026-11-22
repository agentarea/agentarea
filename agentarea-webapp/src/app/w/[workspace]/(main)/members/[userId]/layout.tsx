import type { Metadata } from "next";
import { getTranslations } from "next-intl/server";
import ContentBlock from "@/components/ContentBlock";
import { getViewerCapabilities } from "@/lib/workspace-context";
import { MemberRemoveButton } from "../components/MemberRemoveButton";
import { getMemberHref } from "../components/membersShared";
import { getMemberCached, getMemberTriggersCached } from "./memberDetail";
import MemberDetailTabs from "./MemberDetailTabs";

interface Props {
  params: Promise<{ userId: string }>;
  children: React.ReactNode;
}

export async function generateMetadata({ params }: Props): Promise<Metadata> {
  const { userId } = await params;
  const { label } = await getMemberCached(userId);
  return { title: label };
}

export default async function MemberLayout({ params, children }: Props) {
  const { userId } = await params;
  const [loaded, { canAdminister }, t] = await Promise.all([
    getMemberCached(userId),
    getViewerCapabilities(),
    getTranslations("MembersPage"),
  ]);
  const { member, label } = loaded;
  const triggers = await getMemberTriggersCached(member.user_id);
  const activeTriggers = (triggers ?? []).filter(
    (trigger) => trigger.is_active
  );
  const basePath = getMemberHref(member);
  const isSelf = member.user_id === loaded.currentUser.id;

  return (
    <ContentBlock
      header={{
        breadcrumb: [
          { label: t("title"), href: "/members" },
          { label, href: basePath },
        ],
        controls: (
          <MemberRemoveButton
            member={member}
            currentUser={loaded.currentUser}
            ownerUserId={loaded.ownerUserId}
            workspaceName={loaded.workspaceName ?? t("thisWorkspace")}
            placement="header"
            consequence={
              activeTriggers.length > 0
                ? t(
                    isSelf
                      ? "detail.leaveKeepsAutomations"
                      : "detail.removeKeepsAutomations",
                    { count: activeTriggers.length }
                  )
                : undefined
            }
          />
        ),
      }}
      className="p-0"
      subheader={
        <MemberDetailTabs basePath={basePath} showActivity={canAdminister} />
      }
    >
      {children}
    </ContentBlock>
  );
}
