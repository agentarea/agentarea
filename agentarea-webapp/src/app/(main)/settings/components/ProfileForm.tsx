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
  type OryToastProps,
} from "@ory/elements-react";
import { useSession } from "@ory/elements-react/client";
import { getOryComponents, Settings } from "@ory/elements-react/theme";

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

// Ory notifications also render in the app's global toaster, outside its locale provider.
function SettingsToast({ message }: OryToastProps) {
  return (
    <div
      role={message.type === "error" ? "alert" : "status"}
      data-testid={`ory/message/${message.id}`}
      className="w-full rounded-md border border-border bg-background px-4 py-3 text-sm text-foreground shadow-lg"
    >
      {message.text}
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
        Message: { Toast: SettingsToast },
      }}
    >
      <div className="ory-elements space-y-6">
        <OrySettingsCard />
      </div>
      <SyncProfileSession />
    </Settings>
  );
}
