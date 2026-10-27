"use client";

import { useMemo } from "react";
import { useTranslations } from "next-intl";
import EmptyState from "@/components/EmptyState";
import { useWorkspaceRouter } from "@/hooks/useWorkspaceNavigation";
import type { Policy } from "@/types/policies";
import PoliciesList from "./PoliciesList";
import type { ConnectionNames } from "./policy-rules";

interface AgentOption {
  id: string;
  name: string;
  icon?: string | null;
 
}

interface PoliciesEditableViewProps {
  policies: Policy[];
  agents: AgentOption[];
  connectionNames: ConnectionNames;
}

export default function PoliciesEditableView({
  policies,
  agents,
  connectionNames,
}: PoliciesEditableViewProps) {
  const router = useWorkspaceRouter();
  const t = useTranslations("PoliciesPage");

  const policyById = useMemo(
    () => new Map(policies.map((p) => [p.id, p])),
    [policies]
  );

  const handleEditRule = (ruleId: string) => {
    const policy = policyById.get(ruleId);
    if (!policy) return;
    router.push(`/policies/${policy.id}`);
  };

  return (
    <>
      {policies.length === 0 ? (
        <EmptyState
          title={t("empty.title")}
          description={t("empty.description")}
          iconsType="audit"
          action={{ label: t("newPolicy"), href: "/policies/new" }}
        />
      ) : (
        <PoliciesList
          policies={policies}
          agents={agents}
          connectionNames={connectionNames}
          onEditRule={handleEditRule}
        />
      )}
    </>
  );
}
