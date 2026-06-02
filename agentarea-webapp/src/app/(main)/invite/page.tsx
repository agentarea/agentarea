import type { Metadata } from "next";
import { getTranslations } from "next-intl/server";
import ContentBlock from "@/components/ContentBlock";
import InviteClient from "./InviteClient";

export const metadata: Metadata = {
  title: "Accept invitation",
};

export default async function InvitePage({
  searchParams,
}: {
  searchParams: Promise<{ token?: string }>;
}) {
  const t = await getTranslations("MembersPage");
  const { token } = await searchParams;

  return (
    <ContentBlock
      header={{
        breadcrumb: [{ label: t("acceptTitle") }],
      }}
    >
      <InviteClient token={token ?? null} />
    </ContentBlock>
  );
}
