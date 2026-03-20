"use client";

import { Recovery } from "@ory/elements-react/theme";
import Link from "next/link";

export function RecoveryForm({ flow, config }: { flow: any; config: any }) {
  return (
    <Recovery
      flow={flow}
      config={config}
      components={{
        Card: {
          Footer: () => (
            <div className="ory-elements">
              <div className="text-[0.75rem] text-muted-foreground pt-2 px-0 pb-2">
                Already have an account?{" "}
                <Link href="/auth/login" className="text-[#2252b3] font-medium hover:underline">
                  Sign in
                </Link>
              </div>
            </div>
          ),
        },
      }}
    />
  );
}
