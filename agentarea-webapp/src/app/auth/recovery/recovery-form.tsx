"use client";

import { Recovery } from "@ory/elements-react/theme";
import Link from "next/link";
import { OryClientConfiguration } from "@ory/elements-react";
import type { RecoveryFlow } from "@ory/client-fetch";

interface RecoveryFormProps {
  flow: RecoveryFlow;
  config: OryClientConfiguration;
}

const RecoveryFooter = () => (
  <div className="ory-elements">
    <div className="text-[0.75rem] text-muted-foreground pt-2 px-0 pb-2">
      Already have an account?{" "}
      <Link href="/auth/login" className="text-[#2252b3] font-medium hover:underline">
        Sign in
      </Link>
    </div>
  </div>
);

export const RecoveryForm = ({ flow, config }: RecoveryFormProps) => {
  return (
    <Recovery
      flow={flow}
      config={config}
      components={{
        Card: {
          Footer: RecoveryFooter,
        },
      }}
    />
  );
};
