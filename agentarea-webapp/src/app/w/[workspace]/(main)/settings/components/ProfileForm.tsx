"use client";

import { useEffect } from "react";
import { FlowType, type SettingsFlow } from "@ory/client-fetch";
import {
  OrySettingsCard,
  useOryFlow,
  type OryClientConfiguration,
  type OryFormSectionContentProps,
  type OryFormSectionFooterProps,
  type OryNodeInputProps,
} from "@ory/elements-react";
import { useSession } from "@ory/elements-react/client";
import { getOryComponents, Settings } from "@ory/elements-react/theme";
import FormError from "@/components/FormError";

const DefaultInput = getOryComponents().Node.Input;

function ProfileInput(props: OryNodeInputProps) {
  const isEmail = props.inputProps.name === "traits.email";
  const inputProps = {
    ...props.inputProps,
    readOnly: isEmail,
    className: isEmail ? "!bg-muted/50 !text-muted-foreground" : undefined,
  };

  return <DefaultInput {...props} inputProps={inputProps} />;
}

function SettingsSectionContent({
  title,
  description,
  children,
}: OryFormSectionContentProps) {
  return (
    <div className="flex flex-col gap-4 rounded-t-md border border-b-0 border-border bg-background p-5">
      <div className="space-y-1">
        <h2 className="text-sm font-medium text-foreground">{title}</h2>
        <p className="text-xs text-muted-foreground">{description}</p>
      </div>
      {children}
    </div>
  );
}

function SettingsSectionFooter({ children, text }: OryFormSectionFooterProps) {
  return (
    <div className="flex flex-wrap items-center justify-end gap-3 rounded-b-md border border-border bg-muted/30 px-5 py-3 [&_button]:!mt-0 [&_button]:!w-auto [&_button]:!min-w-28">
      {text && (
        <span className="mr-auto text-xs text-muted-foreground">{text}</span>
      )}
      {children}
    </div>
  );
}

function SettingsMessages() {
  const { flow } = useOryFlow();
  const messages = flow.ui.messages ?? [];
  if (messages.length === 0) return null;

  return (
    <div className="space-y-2">
      {messages.map((message, index) =>
        message.type === "error" ? (
          <FormError key={`${message.id}-${index}`}>{message.text}</FormError>
        ) : (
          <p
            key={`${message.id}-${index}`}
            role="status"
            data-testid={`ory/message/${message.id}`}
            className="text-xs text-muted-foreground"
          >
            {message.text}
          </p>
        )
      )}
    </div>
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
      components={{
        Card: { SettingsSectionContent, SettingsSectionFooter },
        Node: { Input: ProfileInput },
      }}
    >
      <div className="ory-elements ory-app-theme space-y-6">
        <SettingsMessages />
        <OrySettingsCard />
      </div>
      <SyncProfileSession />
    </Settings>
  );
}
