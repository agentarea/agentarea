"use client";

import React from "react";
import { useTranslations } from "next-intl";
import { useRouter } from "next/navigation";
import EmptyState from "@/components/EmptyState/EmptyState";

const NotFound = () => {
  const t = useTranslations("404");
  const router = useRouter();

  return (
    <div className="flex h-full min-h-svh items-center justify-center p-6">
      <EmptyState
        title={t("title")}
        description={t("description")}
        iconsType="404"
        className="max-w-[620px]"
        action={{
          label: t("goHome"),
          onClick: () => router.push("/"),
        }}
      />
    </div>
  );
};

export default NotFound;
