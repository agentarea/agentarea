"use client";

import { useTranslations } from "next-intl";
import { Plus } from "lucide-react";
import { Button } from "@/components/ui/button";
import Link from "@/components/WorkspaceLink";

export default function NewChannelButton() {
  const t = useTranslations("ChannelsPage");

  return (
    <Button className="shrink-0" size="xs" asChild>
      <Link href="/channels/new">
        <Plus />
        {t("new")}
      </Link>
    </Button>
  );
}
