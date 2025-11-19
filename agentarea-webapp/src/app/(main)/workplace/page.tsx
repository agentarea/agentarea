import React from "react";
import AuthGuard from "@/components/auth/AuthGuard";
import ContentBlock from "@/components/ContentBlock/ContentBlock";
import FullChat from "@/components/Chat/FullChat";

export default function WorkplacePage() {
  return (
    <AuthGuard>
      <ContentBlock
        header={{
          breadcrumb: [{ label: "Workplace", href: "/workplace" }],
        }}
      >
        <FullChat agent={{ id: "1", name: "Your main assistant" }} startCentered />
      </ContentBlock>
    </AuthGuard>
  );
}
