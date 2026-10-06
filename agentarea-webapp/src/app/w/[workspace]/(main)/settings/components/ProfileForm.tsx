"use client";

import { useEffect, type ComponentPropsWithoutRef } from "react";
import {
  FlowType,
  getNodeId,
  UiNodeGroupEnum,
  type SettingsFlow,
} from "@ory/client-fetch";
import {
  Node,
  OrySettingsFormSection,
  useOryFlow,
  type OryClientConfiguration,
} from "@ory/elements-react";
import { useSession } from "@ory/elements-react/client";
import { Settings } from "@ory/elements-react/theme";
import ConnectedAccountsSection from "./ConnectedAccountsSection";
import { FlowErrors } from "./FlowParts";
import { groupNodes, hiddenNodes } from "./oryNodes";
import PasswordSection from "./PasswordSection";
import ProfileSection from "./ProfileSection";

/** The Kratos groups this page draws, in order, each as its own form. */
const SECTIONS = [
  [UiNodeGroupEnum.Profile, ProfileSection],
  [UiNodeGroupEnum.Password, PasswordSection],
  [UiNodeGroupEnum.Oidc, ConnectedAccountsSection],
] as const;

/** Every section's `<form>`; carries the flow's hidden inputs (the CSRF token). */
function SectionForm({ children, ...props }: ComponentPropsWithoutRef<"form">) {
  const { flow } = useOryFlow();

  return (
    <form {...props}>
      {children}
      {hiddenNodes(groupNodes(flow.ui.nodes, UiNodeGroupEnum.Default)).map(
        (node) => (
          <Node key={getNodeId(node)} node={node} />
        )
      )}
    </form>
  );
}

function SyncProfileSession() {
  const { flow, flowType } = useOryFlow();
  const { refetch } = useSession();

  useEffect(() => {
    if (flowType === FlowType.Settings && flow.state === "success") {
      void refetch();
    }
  }, [flow, flowType, refetch]);

  return null;
}

/**
 * The account half of the settings page — personal info, password and linked
 * sign-in providers — drawn from the Kratos settings flow. Kratos validates
 * and saves; Ory Elements runs each section's form, we only render it.
 */
function AccountSections() {
  const { flow } = useOryFlow();

  return (
    <>
      <FlowErrors />
      {SECTIONS.map(([group, Section]) => {
        const nodes = groupNodes(flow.ui.nodes, group);
        if (nodes.length === 0) return null;
        return (
          <OrySettingsFormSection
            key={group}
            nodes={nodes}
            data-testid={`ory/screen/settings/group/${group}`}
          >
            <Section nodes={nodes} />
          </OrySettingsFormSection>
        );
      })}
    </>
  );
}

export default function ProfileForm({
  flow,
  config,
}: {
  flow: SettingsFlow;
  config: OryClientConfiguration;
}) {
  return (
    <Settings
      flow={flow}
      config={config}
      components={{ Card: { SettingsSection: SectionForm } }}
    >
      <AccountSections />
      <SyncProfileSession />
    </Settings>
  );
}
