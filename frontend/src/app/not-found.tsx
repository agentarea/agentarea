"use client"
import React from 'react';
import EmptyState from '@/components/EmptyState/EmptyState';
import { useTranslations } from 'next-intl';

const NotFound = () => 
{
  const t = useTranslations("404");

  return (
    <div className="content">
      <div className="content-header">
          <h1>{t("title")}</h1>
      </div>

      <EmptyState 
        title={t("404")}
        description={t("description")}
        iconsType="404"
        action={{
          label: t("goHome"),
          href: "/"
        }}
      />
    </div>
  )
}

export default NotFound