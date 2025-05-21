"use client"
import React from 'react';
import EmptyState from '@/components/EmptyState/EmptyState';
import { useTranslations } from 'next-intl';
import ContentBlock from '@/components/ContentBlock/ContentBlock';

const NotFound = () => {
  const t = useTranslations("404");

  return (
    <ContentBlock
      header={{
        title: t("title")
      }}
    >
      <EmptyState 
        title={t("404")}
        description={t("description")}
        iconsType="404"
        action={{
          label: t("goHome"),
          href: "/"
        }}
      />
    </ContentBlock>
  )
}

export default NotFound