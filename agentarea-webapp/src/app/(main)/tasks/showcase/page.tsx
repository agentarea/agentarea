import type { Metadata } from "next";
import ContentBlock from "@/components/ContentBlock";
import { Badge } from "@/components/ui/badge";
import ChatRendererShowcase from "./ChatRendererShowcase";

export const metadata: Metadata = {
  title: "Chat renderer showcase",
};

export default function ChatRendererShowcasePage() {
  return (
    <ContentBlock
      header={{
        breadcrumb: [
          { label: "Tasks", href: "/tasks" },
          { label: "Chat renderer showcase" },
        ],
        controls: <Badge variant="outline">Demo task · local only</Badge>,
      }}
      className="!p-0"
    >
      <ChatRendererShowcase />
    </ContentBlock>
  );
}
